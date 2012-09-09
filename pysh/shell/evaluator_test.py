import os
import shutil
import tempfile
import unittest

import pysh.shell
from pysh.shell.evaluator import DiagnoseIOType
from pysh.shell.evaluator import run
from pysh.shell.pycmd import register_pycmd, IOType, PyCmd
from pysh.shell.parser import Parser
from pysh.shell.tokenizer import Tokenizer

# pysh.shell.builtin shouldn't be included in evaluator_test.py
assert not hasattr(pysh.shell, 'builtin')

class DiagnoseIOTypeTest(unittest.TestCase):
  def setUp(self):
    pass

  def tearDown(self):
    pass

  def parse(self, input):
    tok = Tokenizer(input)
    parser = Parser(tok)
    return parser.parse()

  def testCmd(self):
    ast = self.parse('cat test.txt')
    DiagnoseIOType(ast, {})
    self.assertEquals('ST', ast.inType)
    self.assertEquals('ST', ast.outType)

  def testPyCmd(self):
    ast = self.parse('pycmd test.txt')
    DiagnoseIOType(ast, {})
    self.assertEquals('PY', ast.inType)
    self.assertEquals('PY', ast.outType)

  def testPipe(self):
    ast = self.parse('pycmd | cat test.txt')
    DiagnoseIOType(ast, {})
    self.assertEquals('PY', ast.inType)
    self.assertEquals('ST', ast.outType)

  def testAnd(self):
    ast = self.parse('pycmd && cat test.txt')
    try:
      DiagnoseIOType(ast, {})
      error = False
    except:
      error = True
    self.assertTrue(error)

  def testPyCmdWithNativeBackquote(self):
    def tmp(args, input, options):
      pass
    tmp = PyCmd(tmp, '', inType=IOType.No)
    ast = self.parse('$tmp `/path/to/cmd`')
    DiagnoseIOType(ast, {'tmp': tmp})
    self.assertEquals('ST', ast.inType)
    self.assertEquals('PY', ast.outType)


def PyCmdExample(args, input, options):
  for arg in args:
    yield arg
  if not input:
    return
  for line in input:
    yield line.rstrip('\n')

register_pycmd('pycmd', PyCmdExample)

class TempDir(object):
  def __init__(self):
    self.path = None

  def __enter__(self):
    self.path = tempfile.mkdtemp()
    return self

  def __exit__(self, type, value, traceback):
    if not self.path:
      return
    try:
      shutil.rmtree(self.path)
    except OSError, e:
      if e.errno != 2:
        raise
    self.path = None


class RunTest(unittest.TestCase):
  def setUp(self):
    self.original_dir = os.getcwd()
    self.tmpdir = TempDir()
    self.tmpdir.__enter__()
    os.chdir(self.tmpdir.path)

  def tearDown(self):
    self.tmpdir.__exit__(None, None, None)
    os.chdir(self.original_dir)

  def testRedirect(self):
    run('echo foo bar > out.txt', globals(), locals())
    self.assertEquals('foo bar\n', file('out.txt').read())

  def testAppendRedirect(self):
    run('echo foo > out.txt', globals(), locals())
    run('echo bar >> out.txt', globals(), locals())
    self.assertEquals('foo\nbar\n', file('out.txt').read())

  def testPipe(self):
    file('tmp.txt', 'w').write('a\nb\nc\n')
    run('cat tmp.txt | grep -v b > out.txt', globals(), locals())
    self.assertEquals('a\nc\n', file('out.txt').read())

  def testPipeWithErrorInLeftDoesNotCauseDeadLock(self):
    error = False
    try:
      run('/bin/ls $invalid | /bin/cat', globals(), locals())
    except Exception, e:
      self.assertTrue('invalid' in e.message)
      error = True
    self.assertTrue(error)

  def testVar(self):
    message = 'Hello world.'
    run('echo $message > out.txt', globals(), locals())
    self.assertEquals('Hello world.\n', file('out.txt').read())

  def testGlobalVar(self):
    run('echo $__name__ > out.txt', globals(), locals())
    self.assertEquals('__main__\n', file('out.txt').read())

  def testFreeVarInLambda(self):
    k = 10
    run('echo ${(lambda x: x + k)(3)} > out.txt', globals(), locals())
    self.assertEquals('13\n', file('out.txt').read())

  def testBuiltinVar(self):
    map_str = str(map)
    run('echo $map > out.txt', globals(), locals())
    self.assertEquals(map_str + '\n', file('out.txt').read())

  def testExpression(self):
    map_str = str(map)
    run('echo ${{len("abc") :[3 * 4 + 10]}} > out.txt',
        globals(), locals())
    self.assertEquals('{3: [22]}\n', file('out.txt').read())

  def testListComprehension(self):
    def tmp(args, input, options):
      return [x * x for x in xrange(3)]
    run('$tmp ${[x * x for x in xrange(3)]} > out.txt',
        globals(), locals())
    self.assertEquals('0\n1\n4\n', file('out.txt').read())

  def testEnvVar(self):
    os.environ['YUNABE_PYSH_TEST_VAR'] = 'foobarbaz'
    run('echo $YUNABE_PYSH_TEST_VAR > out.txt', globals(), locals())
    self.assertEquals('foobarbaz\n', file('out.txt').read())

  def testStringArgs(self):
    run('python -c "import sys;print sys.argv" '
             '"a b" \'c d\' e f > out.txt', globals(), locals())
    argv = eval(file('out.txt').read())
    self.assertEquals(['-c', 'a b', 'c d', 'e', 'f'], argv)

  def testListArgs(self):
    args = ['a', 'b', 10, {1: 3}]
    run('python -c "import sys;print sys.argv" '
        '$args > out.txt', globals(), locals())
    argv = eval(file('out.txt').read())
    self.assertEquals(['-c', 'a', 'b', '10', '{1: 3}'], argv)

  def testNumberedRedirect(self):
    run('python -c "import sys;'
             'print >> sys.stderr, \'error\';print \'out\'"'
             '> stdout.txt 2> stderr.txt',
             globals(), locals())
    self.assertEquals('error\n', file('stderr.txt').read())
    self.assertEquals('out\n', file('stdout.txt').read())

  def testDivertRedirect(self):
    run('python -c "import sys;'
        'print >> sys.stderr, \'error\';print \'out\'"'
        '>out.txt 2>&1', globals(), locals())
    self.assertEquals('error\nout\n', file('out.txt').read())

  def testPyCmd(self):
     run('echo "foo\\nbar" | pycmd a b c | cat > out.txt',
         globals(), locals())
     self.assertEquals('pycmd\na\nb\nc\nfoo\nbar\n', file('out.txt').read())

  def testPyCmdRedirect(self):
    run('echo "foo" | pycmd a b c > out.txt',
        globals(), locals())
    self.assertEquals('pycmd\na\nb\nc\nfoo\n', file('out.txt').read())

  def testPyCmdSequence(self):
    run('echo "foo" | pycmd bar | pycmd baz | cat > out.txt',
        globals(), locals())
    self.assertEquals('pycmd\nbaz\npycmd\nbar\nfoo\n', file('out.txt').read())

  def testPyCmdInVar(self):
    def tmp(args, input, options):
      return ['tmp', 19]
    run('$tmp > out.txt', globals(), locals())
    self.assertEquals('tmp\n19\n', file('out.txt').read())

  def testPyCmdWithErrorDoesNotCauseDeadLock(self):
    def tmp(args, input, options):
      return ['tmp', 19]
    error = False
    try:
      run('$tmp $invalid', globals(), locals())
    except:
      error = True
    self.assertTrue(error)

  def testPyCmdWithErrorInPipeDoesNotCauseDeadLock(self):
    def tmp(args, input, options):
      return ['tmp', 19]
    def reader(args, input, options):
      list(input)
      return []
    error = False
    try:
      run('$tmp $invalid | $reader', globals(), locals())
    except:
      error = True
    self.assertTrue(error)

  def testAnd(self):
    run('echo hoge >> out.txt && echo piyo >> out.txt',
        globals(), locals())
    self.assertEquals('hoge\npiyo\n', file('out.txt').read())

  def testOr(self):
    run('echo hoge >> out.txt || echo piyo >> out.txt',
        globals(), locals())
    self.assertEquals('hoge\n', file('out.txt').read())

  def testOrAnd(self):
    run('(echo foo >> out.txt || echo bar >> out.txt) && '
        'echo baz >> out.txt', globals(), locals())
    self.assertEquals('foo\nbaz\n', file('out.txt').read())

  def testAndOr(self):
    run('(python -c "import sys;sys.exit(1)" >> out.txt && echo bar) || '
        'echo baz >> out.txt)', globals(), locals())
    self.assertEquals('baz\n', file('out.txt').read())

  def testAndNot(self):
    run('python -c "import sys;sys.exit(1)" > out.txt && '
        'echo foo >> out.txt', globals(), locals())
    self.assertEquals('', file('out.txt').read())

  def testOrNot(self):
    run('python -c "import sys;sys.exit(1)" > out.txt || '
        'echo foo >> out.txt', globals(), locals())
    self.assertEquals('foo\n', file('out.txt').read())

  def testAndPyCmd(self):
    def tmp(args, input, options):
      return ['tmp']
    run('$tmp > out.txt && $tmp >> out.txt', globals(), locals())
    self.assertEquals('tmp\ntmp\n', file('out.txt').read())

  def testOrPyCmd(self):
    def tmp(args, input, options):
      return ['tmp']
    run('$tmp > out.txt || $tmp >> out.txt', globals(), locals())
    self.assertEquals('tmp\n', file('out.txt').read())

  def testAndNotPyCmd(self):
    def tmp(args, input, options):
      yield 'a'
      raise Exception('Error!')
    run('$tmp > out.txt && $tmp >> out.txt', globals(), locals())
    self.assertEquals('a\n', file('out.txt').read())

  def testOrNotPyCmd(self):
    def tmp(args, input, options):
      yield 'a'
      raise Exception('Error!')
    run('$tmp > out.txt || $tmp >> out.txt', globals(), locals())
    self.assertEquals('a\na\n', file('out.txt').read())

  def testReturnCode(self):
    rc = run('python -c "import sys;sys.exit(7)" -> rc',
             globals(), locals())
    self.assertEquals(1, len(rc))
    self.assertEquals(True, os.WIFEXITED(rc['rc']))
    self.assertEquals(7, os.WEXITSTATUS(rc['rc']))

  def testReturnCodeMulti(self):
    rc = run('(echo foo >> /dev/null -> rc0) && '
             '(echo bar >> /dev/null -> rc1)', globals(), locals())
    self.assertEquals(2, len(rc))
    self.assertEquals(0, rc['rc0'])
    self.assertEquals(0, rc['rc1'])

  def testStoreOutput(self):
    file('tmp.txt', 'w').write('hello\nworld\n\npiyo')
    rc = run('cat tmp.txt => out', globals(), locals())
    self.assertEquals(['hello', 'world', '', 'piyo'], rc['out'])

  def testStoreOutputWithPyCmd(self):
    rc = run('echo foo | pycmd a b => out', globals(), locals())
    self.assertEquals(['pycmd', 'a', 'b', 'foo'], rc['out'])

  def testSemiColon(self):
    rc = run('echo foo >> out.txt; echo bar >> out.txt',
             globals(), locals())
    self.assertEquals('foo\nbar\n', file('out.txt').read())

  def testExpandUser(self):
    rc = run('echo ~/test.txt > out.txt', globals(), locals())
    path = os.path.expanduser('~/test.txt')
    self.assertEquals(path + '\n', file('out.txt').read())

  def testGlob(self):
    run('echo foo > foo.txt', globals(), locals())
    run('echo bar > bar.txt', globals(), locals())
    run('echo baz > baz.doc', globals(), locals())
    run('echo test > "a*b.doc"', globals(), locals())
    run('echo *.txt > out1.txt', globals(), locals())
    run('echo "*.txt" > out2.txt', globals(), locals())
    run('echo *\'*\'*.doc > out3.txt', globals(), locals())
    self.assertEquals('bar.txt foo.txt\n', file('out1.txt').read())
    self.assertEquals('*.txt\n', file('out2.txt').read())
    self.assertEquals('a*b.doc\n', file('out3.txt').read())

  def testBackQuote(self):
    run('python -c "import sys;print \':\'.join(sys.argv)" '
        '`echo foo bar` > out.txt', globals(), locals())
    self.assertEquals('-c:foo:bar\n', file('out.txt').read())

  def testBackQuoteEmptyOutput(self):
    run('echo `echo`', globals(), locals())

  def testBackQuoteWIthPrefixSuffix(self):
    run('python -c "import sys;print \':\'.join(sys.argv)" '
        'hoge`echo foo bar`piyo > out.txt', globals(), locals())
    self.assertEquals('-c:hogefoo:barpiyo\n', file('out.txt').read())

  def testBackQuoteWIthGlob(self):
    run('echo foo > foo.txt', globals(), locals())
    run('echo bar > bar.txt', globals(), locals())
    run('python -c "import sys;print \':\'.join(sys.argv)" '
        '*`echo .txt` > out.txt', globals(), locals())
    self.assertEquals('-c:bar.txt:foo.txt\n', file('out.txt').read())

  def testBackQuoteInRedirect(self):
    run('echo foo > `echo out.txt`', globals(), locals())
    self.assertEquals('foo\n', file('out.txt').read())

  def testErrorInBackQuoteNoDeadLock(self):
    error = False
    try:
      run('echo `echo $invalid`', globals(), locals())
    except:
      error = True
    self.assertTrue(error)

  def testPipeInBackQuote(self):
    run('python -c "import sys;print \':\'.join(sys.argv)" '
        '`echo foo bar | cat` > out.txt', globals(), locals())
    self.assertEquals('-c:foo:bar\n', file('out.txt').read())

  def testPyCmdInBackQuote(self):
    run('python -c "import sys;print \':\'.join(sys.argv)" '
        '`echo a | pycmd b c` > out.txt', globals(), locals())
    self.assertEquals('-c:pycmd:b:c:a\n', file('out.txt').read())

  def testPyCmdReadInBackQuote(self):
    run('echo foo bar | pycmd a `pycmd 1 2` b | cat > out.txt',
        globals(), locals())
    self.assertEquals('pycmd\na\npycmd\n1\n2\nfoo\nbar\nb\n',
                      file('out.txt').read())

  def testPyCmdAndNativeBackquote(self):
    def tmp(args, input, options):
      return args
    tmp = PyCmd(tmp, '', inType=IOType.No)
    run('$tmp `echo foo bar` > out.txt', globals(), locals())
    self.assertTrue(file('out.txt').read().endswith('\nfoo\nbar\n'))

  def testPyCmdNoInputWithNative(self):
    def tmp(args, input, options):
      return ['bar']
    tmp = PyCmd(tmp, '', inType=IOType.No)
    run('(echo foo && $tmp) | cat > out.txt', globals(), locals())
    self.assertEquals('foo\nbar\n',
                      file('out.txt').read())

  def testPyCmdNoInputWithPycmd(self):
    def tmp(args, input, options):
      return ['bar']
    def pycmd(args, input, options):
      return ['foo']
    tmp = PyCmd(tmp, '', inType=IOType.No)
    run('($pycmd && $tmp) | cat > out.txt', globals(), locals())
    self.assertEquals('foo\nbar\n', file('out.txt').read())
  
  def testPyCmdNoInput_inputNone(self):
    def tmp(args, input, options):
      return [str(input)]
    tmp = PyCmd(tmp, '', inType=IOType.No)
    run('$tmp > out.txt', globals(), locals())
    self.assertEquals('None\n', file('out.txt').read())

  def testPyCmdNoInput_outputIgnored(self):
    def tmp(args, input, options):
      return ['foo']
    tmp = PyCmd(tmp, '', inType=IOType.No, outType=IOType.No)
    response = run('$tmp > out.txt -> rc', globals(), locals())
    self.assertEquals('', file('out.txt').read())
    self.assertTrue(response['rc'] != 0)

  def testPyCmdFileOutput(self):
    def tmp(args, input, options):
      return [1, 2, 3]
    def represent(args, input, options):
      return (repr(e.rstrip('\r\n')) for e in input)
    tmp = PyCmd(tmp, '', outType=IOType.File)
    run('$tmp | $represent > out.txt', globals(), locals())
    # Outputs of pycmd with IOType.File is converted to file stream.
    self.assertEquals('\'1\'\n\'2\'\n\'3\'\n', file('out.txt').read())

  def testPyCmdPipeBothOutput(self):
    def tmp0(args, input, options):
      return [1, 2, 3]
    def tmp1(args, input, options):
      return [4, 5, 6]
    def represent(args, input, options):
      return (repr(e.rstrip('\r\n')) for e in input)
    tmp0 = PyCmd(tmp0, '', outType=IOType.File)
    run('($tmp0 && $tmp1) | cat > out.txt', globals(), locals())
    self.assertEquals('1\n2\n3\n4\n5\n6\n', file('out.txt').read())

  def testPyCmdFileInput(self):
    def tmp(args, input, options):
      return [1, 2, 3]
    def represent(args, input, options):
      return (repr(e.rstrip('\r\n')) for e in input)
    represent = PyCmd(represent, '', inType=IOType.File)
    run('$tmp | $represent > out.txt', globals(), locals())
    self.assertEquals('\'1\'\n\'2\'\n\'3\'\n', file('out.txt').read())

  def testNoDeadLock_pipeAndBackquote(self):
    def tmp(args, input, options):
      return []
    tmp = PyCmd(tmp, '', inType=IOType.No)
    error = False
    try:
      run('$tmp `echo foo` > /invalid/path/1831 | '
          '$tmp `echo piyo` > /invalid/path/1928', globals(), locals())
    except IOError:
      error = True
    self.assertTrue(error)

  def testNoDeadLock_pipeRightCommandEarlyReturn(self):
    # Usually, echo bar exits earlier than echo `echo foo`
    run('echo `echo foo` | echo bar > /dev/null', globals(), locals())


if __name__ == '__main__':
  unittest.main()
