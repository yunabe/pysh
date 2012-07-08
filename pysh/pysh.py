import csv
import glob
import os
import parser
import re
import tokenize
import token
import StringIO
import subprocess
import sys
import threading

SPACE = 'space'
SINGLE_QUOTED_STRING = 'single_quoted'
DOUBLE_QUOTED_STRING = 'double_quoted'
SUBSTITUTION = 'substitution'
REDIRECT = 'redirect'
PIPE = 'pipe'
RIGHT_ARROW = 'right_arrow'
BOLD_RIGHT_ARROW = 'bright_arrow'
LITERAL = 'literal'
AND_OP = 'andop'
OR_OP = 'orop'
PARENTHESIS_START = 'parenthesis_start'
PARENTHESIS_END = 'parenthesis_end'
SEMICOLON = 'semicolon'
BACKQUOTE = 'bquote'
EOF = 'eof'

SPACE_SENSITIVE = set((SINGLE_QUOTED_STRING, DOUBLE_QUOTED_STRING,
                       SUBSTITUTION, LITERAL, BACKQUOTE))

REDIRECT_PATTERN = re.compile(r'(\d*)>(>)?(?:&(\d+))?')
SPACE_PATTERN = re.compile(r'[ \t]+')
VARIABLE_PATTERN = re.compile(r'\$[_a-zA-Z][_a-zA-Z0-9]*')
PIPE_PATTERN = re.compile(r'\|')
RIGHT_ARROW_PATTERN = re.compile(r'\->')
BOLD_RIGHT_ARROW_PATTERN = re.compile(r'\=>')
SINGLE_DOLLAR_PATTERN = re.compile(r'\$')
AND_OPERATOR_PATTERN = re.compile(r'&&')
PARENTHESIS_START_PATTERN = re.compile(r'\(')
PARENTHESIS_END_PATTERN = re.compile(r'\)')
OR_OPERATOR_PATTERN = re.compile(r'\|\|')
SEMICOLON_PATTERN = re.compile(r';')
BACKQUOTE_PATTERN = re.compile(r'`')
LITERAL_PATTERN = re.compile(r'([0-9A-Za-z\!\#\%\*\+\,\.\/\:'
                             r'\?\@\[\\\]\^\_\{\}\~]'
                             r'|\-(?!>)|\=(?!>))+')

PYTHON_VARIABLE_PATTERN = re.compile(r'[_a-zA-Z][_a-zA-Z0-9]*')


class RegexMather(object):
  def __init__(self, regex, type):
    self.__pattern = re.compile(regex)
    self.__type = type

  def consume(self, input):
    match = self.__pattern.match(input) 
    if not match:
      return None, None, 0
    string = match.group(0)
    consumed = len(string)
    input = input[consumed:]
    return self.__type, string, consumed


class StringMatcher(object):
  def consume(self, input):
    type = None
    if input.startswith('"'):
      type = DOUBLE_QUOTED_STRING
    elif input.startswith('\''):
      type = SINGLE_QUOTED_STRING

    if type is not None:
      toks = tokenize.generate_tokens(StringIO.StringIO(input).readline)
      tok = toks.next()
      if tok[0] == token.STRING:
        return type, tok[1], len(tok[1])
      else:
        raise Exception('Wrong string format')
    else:
      return None, None, 0


class ExprMatcher(object):
  def consume(self, input):
    if not input.startswith('${'):
      return None, None, 0
    input = input[2:]
    try:
      parser.expr(input)
      raise Exception('Expected } but EOF found.')
    except SyntaxError, e:
      if input[e.offset - 1] != '}':
        raise
    expr = input[:e.offset - 1]
    parser.expr(expr)
    string = '${%s}' % expr
    return SUBSTITUTION, string, len(string)


class Tokenizer(object):
  def __init__(self, input,
               global_alias_only=False, alias_map=None, alias_history=None):
    self.cur = None
    self.__next = None
    self.__input = input.strip()
    self.__global_alias_only = global_alias_only
    self.__tokens = []
    self.__alias_map = alias_map
    self.__eof = False
    self.__alias_history = alias_history or set()
    self.__matchers = [
      RegexMather(REDIRECT_PATTERN, REDIRECT),
      RegexMather(AND_OPERATOR_PATTERN, AND_OP),
      # should precede PIPE_PATTERN
      RegexMather(OR_OPERATOR_PATTERN, OR_OP),
      RegexMather(PIPE_PATTERN, PIPE),
      RegexMather(RIGHT_ARROW_PATTERN, RIGHT_ARROW),
      RegexMather(BOLD_RIGHT_ARROW_PATTERN, BOLD_RIGHT_ARROW),
      RegexMather(PARENTHESIS_START_PATTERN, PARENTHESIS_START),
      RegexMather(PARENTHESIS_END_PATTERN, PARENTHESIS_END),
      RegexMather(SEMICOLON_PATTERN, SEMICOLON),
      RegexMather(BACKQUOTE_PATTERN, BACKQUOTE),
      StringMatcher(),
      RegexMather(VARIABLE_PATTERN, SUBSTITUTION),
      ExprMatcher(),
      RegexMather(SINGLE_DOLLAR_PATTERN, LITERAL),
      RegexMather(SPACE_PATTERN, SPACE),
      RegexMather(LITERAL_PATTERN, LITERAL),
      ]

  def __iter__(self):
    return self

  def next(self):
    if not self.cur:
      self.cur = self.__get_next()
    else:
      if self.cur[0] == EOF:
        raise StopIteration()
      self.cur = self.__next
      self.__next = None
    if self.cur and self.cur[0] == EOF:
      return self.cur

    self.__next = self.__get_next()
    while True:
      # skip space toke if it's unnecessary.
      # Please note that we call break if self.__next is EOF.
      if self.__next[0] == SPACE and not self.cur[0] in SPACE_SENSITIVE:
        self.__next = self.__get_next()
      elif self.cur[0] == SPACE and not self.__next[0] in SPACE_SENSITIVE:
        self.cur = self.__next
        self.__next = self.__get_next()
      else:
        break
    return self.cur

  def __get_next(self):
    if self.__tokens:
      next = self.__tokens[0]
      self.__tokens = self.__tokens[1:]
    else:
      next = self.__next_exalias()
    self.__global_alias_only = True
    return next

  def __is_literal_like(self, tok):
    return (tok[0] == LITERAL or tok[0] == SINGLE_QUOTED_STRING or
            tok[0] == DOUBLE_QUOTED_STRING or tok[0] == SUBSTITUTION)

  def __next_exalias(self):
    # If tok is literal, try to expand alias.
    tok = self.__next_internal()
    if tok[0] != LITERAL or (self.cur and self.__is_literal_like(self.cur)):
      return tok

    next = self.__next_internal()
    if self.__is_literal_like(next):
      self.__tokens.append(next)
      return tok

    expanded = self.__expand_alias(tok[1])
    if expanded:
      self.__tokens.extend(expanded[1:])
      self.__tokens.append(next)
      return expanded[0]
    else:
      return next

  def __expand_alias(self, text):
    if (not self.__alias_map or text in self.__alias_history or
        not text in self.__alias_map):
      return [(LITERAL, text)]

    alias, is_global = self.__alias_map[text]
    if self.__global_alias_only and not is_global:
      return [(LITERAL, text)]
    self.__alias_history.add(text)
    alias_tokenizer = Tokenizer(alias,
                                global_alias_only=self.__global_alias_only,
                                alias_map=self.__alias_map,
                                alias_history=self.__alias_history)
    # strip eof
    result = list(alias_tokenizer)[:-1]
    self.__alias_history.remove(text)
    return result

  def __next_internal(self):
    input = self.__input
    if not input:
      if self.__eof:
        raise StopIteration()
      else:
        self.__eof = True
        return EOF, ''

    for matcher in self.__matchers:
      token, string, consumed = matcher.consume(input)
      if token is not None:
        self.__input = self.__input[consumed:]
        if token == SPACE:
          return token, ' '
        else:
          return token, string

    raise Exception('Failed to tokenize: ' + self.__input[:100])


class Process(object):
  def __init__(self, args, redirects):
    self.args = args
    self.redirects = redirects

  def __str__(self):
    return '<Process(args=%s, redirects=%s)>' % (self.args, self.redirects)

  def __repr__(self):
    return str(self)


class Parser(object):
  def __init__(self, tokenizer):
    self.__tokenizer = tokenizer

  def parse(self):
    self.__in_bquote = False
    tok, string = self.__tokenizer.next()
    return self.parseExpr()

  def parseExpr(self):
    left = None
    while True:
      assign = self.parseAndOrTest()
      left = (';', left, assign) if left else assign
      tok, _ = self.__tokenizer.cur
      if tok != SEMICOLON:
        return left
      self.__tokenizer.next()
      tok, _ = self.__tokenizer.cur
      if tok == EOF or tok == PARENTHESIS_END or tok == BACKQUOTE:
        return left

  def parseAndOrTest(self):
    left = None
    op = None
    while True:
      piped = self.parsePiped()
      if left:
        left = (op, left, piped)
      else:
        left = piped
      tok, _ = self.__tokenizer.cur
      if tok == AND_OP:
        op = '&&'
        self.__tokenizer.next()
      elif tok == OR_OP:
        op = '||'
        self.__tokenizer.next()
      else:
        return left

  def parsePiped(self):
    left = self.parseCmd()
    while True:
      tok, _ = self.__tokenizer.cur
      if tok == PIPE:
        self.__tokenizer.next()
        cmd = self.parseCmd()
        left = ('|', left, cmd)
      elif tok == RIGHT_ARROW:
        self.__tokenizer.next()
        tok, string = self.__tokenizer.cur
        if tok != LITERAL or not PYTHON_VARIABLE_PATTERN.match(string):
          raise Exception('-> must be followed with python var.')
        self.__tokenizer.next()
        left = ('->', left, string)
      else:
        return left

  def parseCmd(self):
    tok, _ = self.__tokenizer.cur
    if tok == PARENTHESIS_START:
      self.__tokenizer.next()
      expr = self.parseExpr()
      tok, _ = self.__tokenizer.cur
      if tok != PARENTHESIS_END:
        raise Exception('Parenthesis mismatch')
      self.__tokenizer.next()
      return expr
    else:
      return self.parseProcess()

  def parseProcess(self):
    args = []
    redirects = []
    args.append(self.parseArg())
    while True:
      tok, string = self.__tokenizer.cur
      if tok == SPACE:
        self.__tokenizer.next()
        if self.__tokenizer.cur[0] == BACKQUOTE and self.__in_bquote:
          # A hack to ignore space in backquote
          break
        args.append(self.parseArg())
      elif tok == REDIRECT:
        append, src_num, dst_num = self.parseRedirectToken((tok, string))
        self.__tokenizer.next()
        if dst_num != -1:
          redirects.append((append, src_num, dst_num))
        else:
          target = self.parseArg()
          redirects.append((append, src_num, target))
      elif tok == BOLD_RIGHT_ARROW:
        self.__tokenizer.next()
        tok, string = self.__tokenizer.cur
        if tok != LITERAL or not PYTHON_VARIABLE_PATTERN.match(string):
          raise Exception('=> must be followed with python var.')
        redirects.append(('=>', string))
        self.__tokenizer.next()
      else:
        break
    return Process(args, redirects)

  def parseRedirectToken(self, tok):
    m = REDIRECT_PATTERN.match(tok[1])
    src_num = sys.stdout.fileno()
    if m.group(1):
      src_num = int(m.group(1))
    append = False
    if m.group(2):
      append = True
    dst_num = -1
    if m.group(3):
      dst_num = int(m.group(3))
    if append and dst_num != -1:
      raise Exception('Can not use both >> and &%d.' % dst_num)
    return append, src_num, dst_num

  def parseArg(self):
    result = []
    while True:
      tok, string = self.__tokenizer.cur
      if self.isArgToken(tok):
        self.appendToken((tok, string), result)
        self.__tokenizer.next()
      elif tok == BACKQUOTE and not self.__in_bquote:
        result.append(self.parseBackQuote())
      else:
        break
    if not result:
      raise Exception('Unexpected token: %s: %s' % (tok, string))
    return result

  def isArgToken(self, tok):
    return (tok == LITERAL or
            tok == SINGLE_QUOTED_STRING or
            tok == DOUBLE_QUOTED_STRING or
            tok == SUBSTITUTION)

  def appendToken(self, tok, tokens):
    if tok[0] == DOUBLE_QUOTED_STRING:
      tokens.extend(DoubleQuotedStringExpander(eval(tok[1])))
    else:
      tokens.append(tok)

  def parseBackQuote(self):
    while self.__tokenizer.next()[0] == SPACE:
      # A hack to ignore space in backquote
      pass
    self.__in_bquote = True
    expr = self.parseExpr()
    self.__in_bquote = False
    tok, _ = self.__tokenizer.cur
    if tok != BACKQUOTE:
      raise Exception('backquote mismatch')
    self.__tokenizer.next()
    return (BACKQUOTE, expr)


class DoubleQuotedStringExpander(object):
  def __init__(self, input):
    self.__input = input
    self.__var_matcher = RegexMather(VARIABLE_PATTERN, SUBSTITUTION)
    self.__expr_matcher = ExprMatcher()
    
  def __iter__(self):
    return self

  def next(self):
    input = self.__input
    if not input:
      raise StopIteration()
    if input[0] == '$':
      token, string, consumed = self.__var_matcher.consume(input)
      if token is None:
        token, string, consumed = self.__expr_matcher.consume(input)
      if token is None:
        token, string, consumed = LITERAL, '$', 1
      self.__input = input[consumed:]
      return token, string
    else:
      pos = input.find('$')
      if pos == -1:
        self.__input = ''
        return SINGLE_QUOTED_STRING, repr(input)
      else:
        self.__input = input[pos:]
        return SINGLE_QUOTED_STRING, repr(input[:pos])


class VarDict(object):
  def __init__(self, globals, locals):
    # We need to maintain __temporary because list comprehension need to
    # modify local variables in Python 2.x.
    self.__temporary = None
    self.__globals = globals
    self.__locals = locals

  def __getitem__(self, key):
    if self.__temporary and key in self.__temporary:
      return self.__temporary[key]
    if key in self.__locals:
      return self.__locals[key]
    if key in self.__globals:
      return self.__globals[key]
    if key in os.environ:
      return os.environ[key]
    if hasattr(__builtins__, key):
      return getattr(__builtins__, key)
    raise KeyError(key)

  def __delitem__(self, key):
    if self.__temporary:
      del self.__temporary[key]

  def __setitem__(self, key, value):
    if self.__temporary is None:
      self.__temporary = {}
    self.__temporary[key] = value


__pycmd_map = {}


def register_pycmd(name, pycmd):
  __pycmd_map[name] = pycmd


def get_pycmd(name):
  if isinstance(name, str) and name in __pycmd_map:
    return __pycmd_map[name]
  elif hasattr(name, 'process'):
    return name
  else:
    return None

# TODO: handle exception in run correctly.
class PyCmdRunner(threading.Thread):
  def __init__(self, pycmd_stack, r, w):
    threading.Thread.__init__(self)
    assert pycmd_stack
    self.__pycmd_stack = pycmd_stack
    self.__r = r
    self.__w = w
    self.ok = False

  def dependencies(self):
    result = []
    for _, _, _, dependency in self.__pycmd_stack:
      result.append(dependency)
    return result

  def run(self):
    # Creates w first to close self.__w for sure.
    if self.__w != -1:
      w = os.fdopen(self.__w, 'w')
    else:
      w = sys.stdout
    if self.__r == -1:
      out = None
    else:
      out = os.fdopen(self.__r, 'r')
    for i, (pycmd, args, redirects, _) in enumerate(self.__pycmd_stack):
      if redirects:
        if w is not sys.stdout or i != len(self.__pycmd_stack) - 1:
          raise Exception('redirect with pycmd is allowed '
                          'only when it is the last.')
        if len(redirects) != 1:
          raise Exception('multi-redirect with pycmd is not allowed.')

        redirect = redirects[0]
        if isinstance(redirect[2], int):
          raise Exception('Redirect to another file descriptor is not allowed.')
        if redirect[0]:
          mode = 'a'  # >>
        else:
          mode = 'w'  # >
        w = file(redirect[2], mode)

      out = pycmd.process(args, out)

    for data in out:
      w.write(str(data) + '\n')
      w.flush()  # can be inefficient.
    self.ok = True


class Evaluator(object):
  def __init__(self, parser):
    self.__parser = parser
    self.__rc = {}

  def __after_folk(self, pid):
    pass

  def rc(self):
    return self.__rc

  def evalAst(self, ast, dependency_stack, out):
    if isinstance(ast, Process):
      out.append((ast, dependency_stack))
    elif isinstance(ast, tuple) or isinstance(ast, list):
      if len(ast) != 3:
        raise Exception('Invalid AST format. Wrong length.')
      op = ast[0]
      if op == '&&' or op == '||' or op == ';':
        dependency_stack.append(ast)
        self.evalAst(ast[1], dependency_stack, out)
      elif op == '|':
        self.evalAst(ast[1], [], out)
        self.evalAst(ast[2], dependency_stack, out)
      elif op == '<-':
        dependency_stack.append(ast)
        self.evalAst(ast[2], dependency_stack, out)
      elif op == '->':
        dependency_stack.append(ast)
        self.evalAst(ast[1], dependency_stack, out)
      else:
        raise Exception('Unknown operator: %s' % op)
    else:
      raise Exception('Invalid AST format.')

  def evalSubstitution(self, value, globals, locals):
    if value.startswith('${'):
      # remove ${ and }
      name = value[2:-1]
    else:
      # remove $
      name = value[1:]
    return eval(name, None, VarDict(globals, locals))

  def evalArg(self, arg, globals, locals):
    assert arg
    arg = self.evalBackquotedCmd(arg, globals, locals)
    if not self.hasGlobPattern(arg):
      return self.evalArgNoGlob(arg, globals, locals)
    else:
      return self.evalArgGlob(arg, globals, locals)

  def evalBackquotedCmd(self, arg, globals, locals):
    result = []
    for tok in arg:
      if tok[0] == BACKQUOTE:
        raise Exception('Evaluation of backquote is not supported.')
      else:
        result.append(tok)
    return result
  
  def evalArgNoGlob(self, arg, globals, locals):
    values = []
    for tok in arg:
      if tok[0] == LITERAL:
        values.append(tok[1])
      elif tok[0] == SINGLE_QUOTED_STRING:
        values.append(eval(tok[1]))
      elif tok[0] == SUBSTITUTION:
        values.append(self.evalSubstitution(tok[1], globals, locals))
      else:
        raise Exception('Unexpected token: %s' % tok[0])
    if len(values) > 1:
      result = ''.join(map(str, values))
    else:
      result = values[0]
    if isinstance(result, str):
      result = os.path.expanduser(result)
    return [result]

  def evalArgGlob(self, arg, globals, locals):
    values = []
    for tok in arg:
      if tok[0] == LITERAL:
        values.append(tok[1])
      elif tok[0] == SINGLE_QUOTED_STRING:
        values.append(eval(tok[1]).replace('*', '[*]').replace('?', '[?]'))
      elif tok[0] == SUBSTITUTION:
        values.append(
          self.evalSubstitution(tok[1], globals, locals).replace(
            '*', '[*]').replace('?', '[?]'))
      else:
        raise Exception('Unexpected token: %s' % tok[0])
    result = ''.join(map(str, values))
    expanded = glob.glob(os.path.expanduser(result))
    # Make order of glob expansion stable.
    expanded.sort()
    return expanded

  def convertToCmdArgs(self, arg):
    if isinstance(arg, list):
      return map(str, arg)
    else:
      return [str(arg)]

  def hasGlobPattern(self, arg):
    for tok in arg:
      if tok[0] == LITERAL:
        if '*' in tok[1] or '?' in tok[1]:
          return True
    return False

  def execute(self, globals, locals):
    ast = self.__parser.parse()
    self.executeAst(ast, globals, locals)

  def executeAst(self, ast, globals, locals):
    pids = {}
    procs = []
    self.evalAst(ast, [], procs)
    procs_queue = [procs]

    # TODO: Improve task parallelism.
    while procs_queue:
      procs = procs_queue[0]
      procs_queue = procs_queue[1:]
      pycmd_runners = []
      self.executeProcs(procs, globals, locals, pids, pycmd_runners)

      for runner in pycmd_runners:
        runner.join()
        for dependency in runner.dependencies():
          new_procs = self.continueFromDependency(
            0 if runner.ok else 1, dependency)
          if new_procs:
            procs_queue.append(new_procs)

      while len(pids) > 0:
        pid, rc = os.wait()
        dependency = pids.pop(pid)
        new_procs = self.continueFromDependency(rc, dependency)
        if new_procs:
          procs_queue.append(new_procs)

  def continueFromDependency(self, rc, dependency_stack):
    ok = rc == 0
    while True:
      if not dependency_stack:
        return None
      op, left, right = dependency_stack.pop()
      if op == '<-':
        self.storeReturnCode(left, rc)
      elif op == '->':
        self.storeReturnCode(right, rc)
      else:
        if (op == ';' or
            (op == '&&' and ok == True) or
            (op == '||' and ok == False)):
          break
    procs = []
    self.evalAst(right, dependency_stack, procs)
    return procs

  def storeReturnCode(self, name, rc):
    self.__rc[name] = rc

  def executeProcs(self, procs, globals, locals, pids, pycmd_runners):
    old_r = -1
    pycmd_stack = []
    # We need to store list of write-fd for runners to close them
    # in child process!!
    runner_wfd = []
    for i, (proc, dependency) in enumerate(procs):
      is_last = i == len(procs) - 1
      args = []
      for arg in proc.args:
        args.extend(self.evalArg(arg, globals, locals))
      redirects = []
      for redirect in proc.redirects:
        if redirect[0] == '=>':
          raise Exception('Not supported.')
        if isinstance(redirect[2], int):
          redirects.append(redirect)
        else:
          targets = self.evalArg(redirect[2], globals, locals)
          redirects.append((redirect[0], redirect[1],
                            str(targets[0])))

      pycmd = get_pycmd(args[0])
      if pycmd:
        pycmd_stack.append((pycmd, args, redirects, dependency))
        continue

      if pycmd_stack:
        new_r, w = os.pipe()
        runner = PyCmdRunner(pycmd_stack, old_r, w)
        pycmd_runners.append(runner)
        runner_wfd.append(w)
        old_r = new_r
        pycmd_stack = []

      if not is_last:
        new_r, w = os.pipe()
      pid = os.fork()
      self.__after_folk(pid)
      if pid != 0:
        if not is_last:
          # Don't forget to close pipe in the root process.
          os.close(w)
        if old_r != -1:
          os.close(old_r)
        pids[pid] = dependency
        if not is_last:
          old_r = new_r
      else:
        for fd in runner_wfd:
          os.close(fd)
        if not is_last:
          os.dup2(w, sys.stdout.fileno())
        if old_r != -1:
          os.dup2(old_r, sys.stdin.fileno())
        for redirect in redirects:
          if isinstance(redirect[2], int):
            os.dup2(redirect[2], redirect[1])
          else:
            if redirect[0]:
              mode = 'a'  # >>
            else:
              mode = 'w'  # >
            f = file(redirect[2], mode)
            os.dup2(f.fileno(), redirect[1])
        str_args = []
        for arg in args:
          str_args.extend(self.convertToCmdArgs(arg))
        try:
          os.execvp(str_args[0], str_args)
        except Exception, e:
          print >> sys.stderr, e
          sys.stderr.flush()
          os._exit(1)

    if pycmd_stack:
      # pycmd is the last command.
      runner = PyCmdRunner(pycmd_stack, old_r, -1)
      pycmd_runners.append(runner)

    for runner in pycmd_runners:
      runner.start()


def file_to_array(f):
  return map(lambda line: line.rstrip('\r\n'), f.readlines())


class pycmd_send(object):
  def process(self, args, input):
    assert len(args) == 2
    return args[1]


class pycmd_recv(object):
  def process(self, args, input):
    if isinstance(input, file):
      input = file_to_array(input)
    assert len(args) == 2
    l = args[1]
    assert isinstance(l, list)
    l.extend(input)
    return []


class pycmd_map(object):
  def process(self, args, input):
    assert len(args) == 2
    if isinstance(input, file):
      input = file_to_array(input)
    f = args[1]
    assert callable(f)
    return (f(x) for x in input)


class pycmd_filter(object):
  def process(self, args, input):
    assert len(args) == 2
    if isinstance(input, file):
      input = file_to_array(input)
    cond = args[1]
    assert callable(cond)
    for x in input:
      if cond(x):
        yield x


class pycmd_reduce(object):
  def process(self, args, input):
    assert len(args) == 2
    if isinstance(input, file):
      input = file_to_array(input)
    f = args[1]
    assert callable(f)
    return [reduce(f, input)]


class pycmd_readcsv(object):
  def process(self, args, input):
    return csv.reader(input)


class pycmd_cd(object):
  def process(self, args, input):
    assert len(args) == 2
    os.chdir(args[1])
    return ()


register_pycmd('send', pycmd_send())
register_pycmd('recv', pycmd_recv())
register_pycmd('map', pycmd_map())
register_pycmd('filter', pycmd_filter())
register_pycmd('reduce', pycmd_reduce())
register_pycmd('readcsv', pycmd_readcsv())
register_pycmd('cd', pycmd_cd())


def run(cmd_str, globals, locals, alias_map=None):
  tok = Tokenizer(cmd_str, alias_map=alias_map)
  parser = Parser(tok)
  evaluator = Evaluator(parser)
  evaluator.execute(globals, locals)
  return evaluator.rc()
