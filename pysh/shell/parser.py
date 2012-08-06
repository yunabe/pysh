import re
import sys  # need test in parser_test

from pysh.shell.tokenizer import (
  SPACE,
  SINGLE_QUOTED_STRING,
  DOUBLE_QUOTED_STRING,
  SUBSTITUTION,
  REDIRECT,
  PIPE,
  RIGHT_ARROW,
  BOLD_RIGHT_ARROW,
  LITERAL,
  AND_OP,
  OR_OP,
  PARENTHESIS_START,
  PARENTHESIS_END,
  SEMICOLON,
  BACKQUOTE,
  EOF,

  VARIABLE_PATTERN,
  REDIRECT_PATTERN, # need test
)

# need test in parser_test
PYTHON_VARIABLE_PATTERN = re.compile(r'[_a-zA-Z][_a-zA-Z0-9]*')

from pysh.shell.tokenizer import ExprMatcher
from pysh.shell.tokenizer import RegexMather


class Process(object):
  def __init__(self, args, redirects):
    self.args = args
    self.redirects = redirects

  def __str__(self):
    return '<Process(args=%s, redirects=%s)>' % (self.args, self.redirects)

  def __repr__(self):
    return str(self)

class BinaryOp(object):
  def __init__(self, op, left, right):
    self.op = op
    self.left = left
    self.right = right

class Assign(object):
  def __init__(self, cmd, name):
    self.cmd = cmd
    self.name = name


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
      left = BinaryOp(';', left, assign) if left else assign
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
        left = BinaryOp(op, left, piped)
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
        left = BinaryOp('|', left, cmd)
      elif tok == RIGHT_ARROW:
        self.__tokenizer.next()
        tok, string = self.__tokenizer.cur
        if tok != LITERAL or not PYTHON_VARIABLE_PATTERN.match(string):
          raise Exception('-> must be followed with python var.')
        self.__tokenizer.next()
        left = Assign(left, string)
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
