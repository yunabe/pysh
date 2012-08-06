import glob
import os
import sys
import threading

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

)

from pysh.shell.parser import Assign
from pysh.shell.parser import Parser
from pysh.shell.parser import Process
from pysh.shell.parser import BinaryOp
from pysh.shell.tokenizer import Tokenizer


class VarDict(dict):
  # VarDict must be a real dict because it is passed to eval as globals.
  def __init__(self, globals, locals):
    for d in (os.environ, globals, locals):
      for key in d:
        self[key] = d[key]


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


class RecvRunner(threading.Thread):
  def __init__(self, r, out):
    self.__r = r
    self.__out = out
    threading.Thread.__init__(self)

  def run(self):
    for line in os.fdopen(self.__r, 'r'):
      self.__out.append(line.rstrip('\r\n'))


# TODO: handle exception in run correctly.
class PyCmdRunner(threading.Thread):
  def __init__(self, rc, pycmd_stack, r, w):
    threading.Thread.__init__(self)
    assert pycmd_stack
    self.__rc = rc
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
        if redirect[2] == 'num':
          raise Exception('Redirect to another file descriptor is not allowed.')
        elif redirect[2] == 'pyout':
          w = []
          self.__rc[redirect[3]] = w
        else:
          if redirect[0]:
            mode = 'a'  # >>
          else:
            mode = 'w'  # >
          w = file(redirect[3], mode)

      out = pycmd.process(args, out)

    if isinstance(w, list):
      for data in out:
        w.append(data)
    else:
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
    elif isinstance(ast, Assign):
      dependency_stack.append(ast)
      self.evalAst(ast.cmd, dependency_stack, out) 
    elif isinstance(ast, BinaryOp):
      if ast.op == '||' or ast.op == '&&' or ast.op == ';':
        dependency_stack.append(ast)
        self.evalAst(ast.left, dependency_stack, out)
      elif ast.op == '|':
        self.evalAst(ast.left, [], out)
        self.evalAst(ast.right, dependency_stack, out)
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
    # We need to pass VarDict as globals because free variable in lambda is
    # treated as global variable in eval (http://goo.gl/bfVW9).
    return eval(name, VarDict(globals, locals), {})

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
      recv_runners = []
      self.executeProcs(
        procs, globals, locals, pids, pycmd_runners, recv_runners)

      for runner in pycmd_runners:
        runner.join()
        for dependency in runner.dependencies():
          new_procs = self.continueFromDependency(
            0 if runner.ok else 1, dependency)
          if new_procs:
            procs_queue.append(new_procs)

      for runner in recv_runners:
        runner.join()

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
      ast = dependency_stack.pop()
      if isinstance(ast, Assign):
        self.storeReturnCode(ast.name, rc)
        continue
      assert isinstance(ast, BinaryOp)
      op, right = ast.op, ast.right
      if (op == ';' or
          (op == '&&' and ok == True) or
          (op == '||' and ok == False)):
        break
    procs = []
    self.evalAst(right, dependency_stack, procs)
    return procs

  def storeReturnCode(self, name, rc):
    self.__rc[name] = rc

  def executeProcs(self, procs, globals, locals,
                   pids, pycmd_runners, recv_runners):
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
          redirects.append((False, 1, 'pyout', redirect[1]))
        elif isinstance(redirect[2], int):
          redirects.append((redirect[0], redirect[1], 'num', redirect[2]))
        else:
          targets = self.evalArg(redirect[2], globals, locals)
          redirects.append((redirect[0], redirect[1], 'file', str(targets[0])))

      pycmd = get_pycmd(args[0])
      if pycmd:
        pycmd_stack.append((pycmd, args, redirects, dependency))
        continue

      if pycmd_stack:
        new_r, w = os.pipe()
        runner = PyCmdRunner(self.__rc, pycmd_stack, old_r, w)
        pycmd_runners.append(runner)
        runner_wfd.append(w)
        old_r = new_r
        pycmd_stack = []

      pyout_rs = []
      pyout_ws = []
      for i, redirect in enumerate(redirects):
        if redirect[2] != 'pyout':
          continue
        pyout_list = []
        self.__rc[redirect[3]] = pyout_list
        pyout_r, pyout_w = os.pipe()
        recv_runners.append(RecvRunner(pyout_r, pyout_list))
        redirects[i] = (redirect[0], redirect[1], redirect[2], pyout_w)
        pyout_rs.append(pyout_r)
        pyout_ws.append(pyout_w)

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
        for fd in pyout_ws:
          os.close(fd)
        pids[pid] = dependency
        if not is_last:
          old_r = new_r
      else:
        for fd in runner_wfd:
          os.close(fd)
        for fd in pyout_rs:
          os.close(fd)
        if not is_last:
          os.dup2(w, sys.stdout.fileno())
        if old_r != -1:
          os.dup2(old_r, sys.stdin.fileno())
        for redirect in redirects:
          if redirect[2] == 'num':
            os.dup2(redirect[3], redirect[1])
          elif redirect[2] == 'pyout':
            os.dup2(redirect[3], redirect[1])
          else:
            if redirect[0]:
              mode = 'a'  # >>
            else:
              mode = 'w'  # >
            f = file(redirect[3], mode)
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
      runner = PyCmdRunner(self.__rc, pycmd_stack, old_r, -1)
      pycmd_runners.append(runner)

    for runner in pycmd_runners:
      runner.start()
    for runner in recv_runners:
      runner.start()


def run(cmd_str, globals, locals, alias_map=None):
  tok = Tokenizer(cmd_str, alias_map=alias_map)
  parser = Parser(tok)
  evaluator = Evaluator(parser)
  evaluator.execute(globals, locals)
  return evaluator.rc()
