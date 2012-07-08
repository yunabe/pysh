import pysh
from pysh import SPACE
from pysh import SINGLE_QUOTED_STRING
from pysh import DOUBLE_QUOTED_STRING
from pysh import SUBSTITUTION
from pysh import REDIRECT
from pysh import PIPE
from pysh import LEFT_ARROW
from pysh import RIGHT_ARROW
from pysh import BOLD_RIGHT_ARROW
from pysh import LITERAL
from pysh import AND_OP
from pysh import OR_OP
from pysh import PARENTHESIS_START
from pysh import PARENTHESIS_END
from pysh import SEMICOLON
from pysh import BACKQUOTE
from pysh import EOF

import os
import re
import shutil
import tempfile
import unittest

class PyCmd(object):
  def process(self, args, input):
    for arg in args:
      yield arg
    for line in input:
      yield line.rstrip('\n')

pysh.register_pycmd('pycmd', PyCmd())


class RegexMatherTest(unittest.TestCase):
  def test(self):
    pattern = re.compile(r'abc')
    matcher = pysh.RegexMather(pattern, LITERAL)

    type, string, consumed = matcher.consume('abcdefg')
    self.assertEquals(type, LITERAL)
    self.assertEquals(string, 'abc')
    self.assertEquals(consumed, 3)

    type, string, consumed = matcher.consume('abc defg')
    self.assertEquals(type, LITERAL)
    self.assertEquals(string, 'abc')
    self.assertEquals(consumed, 3)

    type, _, _ = matcher.consume(' abcdefg')
    self.assertTrue(type is None)


class TokenizerTest(unittest.TestCase):
  def test0(self):
    tok = pysh.Tokenizer('cat /tmp/www/foo.txt')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def test1(self):
    tok = pysh.Tokenizer('cat        /tmp/www/foo.txt')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def test2(self):
    tok = pysh.Tokenizer(' cat /tmp/www/foo.txt ')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def test2_2(self):
    tok = pysh.Tokenizer('cat\t/tmp/www/foo.txt')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitution(self):
    tok = pysh.Tokenizer('echo $a$b/$c')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '$a'),
                       (SUBSTITUTION, '$b'),
                       (LITERAL, '/'),
                       (SUBSTITUTION, '$c'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionWithSpace(self):
    tok = pysh.Tokenizer('echo $a $b /$c')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '$a'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '$b'),
                       (SPACE, ' '),
                       (LITERAL, '/'),
                       (SUBSTITUTION, '$c'),
                       (EOF, ''),
                       ], list(tok))


  def testSubstitutionWithoutSpace(self):
    tok = pysh.Tokenizer('echo hoge$a')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'hoge'),
                       (SUBSTITUTION, '$a'),
                       (EOF, ''),
                       ], list(tok))

  def testBraceSubstitution(self):
    tok = pysh.Tokenizer('echo hoge${a}')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'hoge'),
                       (SUBSTITUTION, '${a}'),
                       (EOF, ''),
                       ], list(tok))

  def testBraceSubstitutionWithTrailing(self):
    tok = pysh.Tokenizer('echo hoge${a}10')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'hoge'),
                       (SUBSTITUTION, '${a}'),
                       (LITERAL, '10'),
                       (EOF, ''),
                       ], list(tok))

  def testExpression(self):
    tok = pysh.Tokenizer('echo ${{1: 10}}')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '${{1: 10}}'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionUnderscore(self):
    tok = pysh.Tokenizer('echo $__init__')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '$__init__'),
                       (EOF, ''),
                       ], list(tok))

  def testPipe(self):
    tok = pysh.Tokenizer('cat | /tmp/out')
    self.assertEquals([(LITERAL, 'cat'),
                       (PIPE, '|'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))

  def testPipeWithoutSpace(self):
    tok = pysh.Tokenizer('cat|/tmp/out')
    self.assertEquals([(LITERAL, 'cat'),
                       (PIPE, '|'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))


  def testRedirect(self):
    tok = pysh.Tokenizer('echo a>/tmp/out')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'a'),
                       (REDIRECT, '>'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))

  def testRedirectAppend(self):
    tok = pysh.Tokenizer('echo a>>/tmp/out')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'a'),
                       (REDIRECT, '>>'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))

  def testRedirectInvalidName(self):
    tok = pysh.Tokenizer('echo $10')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, '$'),
                       (LITERAL, '10'),
                       (EOF, ''),
                       ], list(tok))

  def testRedirectAppend(self):
    tok = pysh.Tokenizer('echo \'abc\'"def"')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SINGLE_QUOTED_STRING, '\'abc\''),
                       (DOUBLE_QUOTED_STRING, '"def"'),
                       (EOF, ''),
                       ], list(tok))

  def testAndOrOperator(self):
    tok = pysh.Tokenizer('foo && bar || a&&b||c')
    self.assertEquals([(LITERAL, 'foo'),
                       (AND_OP, '&&'),
                       (LITERAL, 'bar'),
                       (OR_OP, '||'),
                       (LITERAL, 'a'),
                       (AND_OP, '&&'),
                       (LITERAL, 'b'),
                       (OR_OP, '||'),
                       (LITERAL, 'c'),
                       (EOF, ''),
                       ], list(tok))

  def testParenthesis(self):
    tok = pysh.Tokenizer('() a(b)')
    self.assertEquals([(PARENTHESIS_START, '('),
                       (PARENTHESIS_END, ')'),
                       (LITERAL, 'a'),
                       (PARENTHESIS_START, '('),
                       (LITERAL, 'b'),
                       (PARENTHESIS_END, ')'),
                       (EOF, '')], list(tok))

  def testLeftArrow(self):
    tok = pysh.Tokenizer('x<-echo')
    self.assertEquals([(LITERAL, 'x'),
                       (LEFT_ARROW, '<-'),
                       (LITERAL, 'echo'),
                       (EOF, '')], list(tok))
    tok = pysh.Tokenizer('x <- echo')
    self.assertEquals([(LITERAL, 'x'),
                       (LEFT_ARROW, '<-'),
                       (LITERAL, 'echo'),
                       (EOF, '')], list(tok))

  def testRightArrow(self):
    tok = pysh.Tokenizer('echo->x')
    self.assertEquals([(LITERAL, 'echo'),
                       (RIGHT_ARROW, '->'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))
    tok = pysh.Tokenizer('echo -> x')
    self.assertEquals([(LITERAL, 'echo'),
                       (RIGHT_ARROW, '->'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))

  def testBoldRightArrow(self):
    tok = pysh.Tokenizer('echo=>x')
    self.assertEquals([(LITERAL, 'echo'),
                       (BOLD_RIGHT_ARROW, '=>'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))
    tok = pysh.Tokenizer('echo => x')
    self.assertEquals([(LITERAL, 'echo'),
                       (BOLD_RIGHT_ARROW, '=>'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))

  def testHyphenEqualInLiteral(self):
    tok = pysh.Tokenizer('echo x- -- -')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'x-'),
                       (SPACE, ' '),
                       (LITERAL, '--'),
                       (SPACE, ' '),
                       (LITERAL, '-'),
                       (EOF, '')], list(tok))
    tok = pysh.Tokenizer('echo x= == =')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'x='),
                       (SPACE, ' '),
                       (LITERAL, '=='),
                       (SPACE, ' '),
                       (LITERAL, '='),
                       (EOF, '')], list(tok))

  def testSemicolon(self):
    tok = pysh.Tokenizer('a;b;')
    self.assertEquals([(LITERAL, 'a'),
                       (SEMICOLON, ';'),
                       (LITERAL, 'b'),
                       (SEMICOLON, ';'),
                       (EOF, '')], list(tok))

  def testSemicolonWithSpace(self):
    tok = pysh.Tokenizer('a ; b ; ')
    self.assertEquals([(LITERAL, 'a'),
                       (SEMICOLON, ';'),
                       (LITERAL, 'b'),
                       (SEMICOLON, ';'),
                       (EOF, '')], list(tok))

  def testBackQuote(self):
    tok = pysh.Tokenizer('echo `echo foo`')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (BACKQUOTE, '`'),
                       (LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'foo'),
                       (BACKQUOTE, '`'),
                       (EOF, '')], list(tok))

  def testBackQuoteWithSpace(self):
    tok = pysh.Tokenizer('echo ` echo foo `')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (BACKQUOTE, '`'),
                       (SPACE, ' '),
                       (LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'foo'),
                       (SPACE, ' '),
                       (BACKQUOTE, '`'),
                       (EOF, '')], list(tok))


class AliasTest(unittest.TestCase):
  def test(self):
    alias_map = {'ls': ('ls -la', False)}
    tok = pysh.Tokenizer('ls /tmp/www/foo.txt', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (SPACE, ' '),
                       (LITERAL, '-la'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def testNotGlobal(self):
    alias_map = {'ls': ('ls -la', False)}
    tok = pysh.Tokenizer('echo ls /tmp/www/foo.txt', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'ls'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def testGlobal(self):
    alias_map = {'GR': ('| grep &&', True)}
    tok = pysh.Tokenizer('ls GR echo', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (PIPE, '|'),
                       (LITERAL, 'grep'),
                       (AND_OP, '&&'),
                       (LITERAL, 'echo'),
                       (EOF, ''),
                       ], list(tok))

  def testRecursive(self):
    alias_map = {'ls': ('ls -la', False),
                 'sl': ('ls', True)}
    tok = pysh.Tokenizer('sl', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (SPACE, ' '),
                       (LITERAL, '-la'),
                       (EOF, ''),
                       ], list(tok))

  def testRecursiveNotGlobal(self):
    alias_map = {'ls': ('ls -la', False),
                 'sl': ('ls', True)}
    tok = pysh.Tokenizer('echo sl', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'ls'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionSuffix(self):
    alias_map = {'ls': ('ls -la', False)}
    tok = pysh.Tokenizer('ls$x', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (SUBSTITUTION, '$x'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionPrefix(self):
    alias_map = {'GR': ('| grep', True)}
    tok = pysh.Tokenizer('${x}GR', alias_map=alias_map)
    self.assertEquals([(SUBSTITUTION, '${x}'),
                       (LITERAL, 'GR'),
                       (EOF, ''),
                       ], list(tok))


class DoubleQuotedStringExpanderTest(unittest.TestCase):
  def test(self):
    expanded = pysh.DoubleQuotedStringExpander(
      'apple pie. a$bc e${fg}\t10 ${{1: "3}"}}')
    self.assertEquals([(SINGLE_QUOTED_STRING, "'apple pie. a'"),
                       (SUBSTITUTION, '$bc'),
                       (SINGLE_QUOTED_STRING, "' e'"),
                       (SUBSTITUTION, '${fg}'),
                       (SINGLE_QUOTED_STRING, "'\\t10 '"),
                       (SUBSTITUTION, '${{1: "3}"}}'),
                       ], list(expanded))


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


class ParserTest(unittest.TestCase):
  def test(self):
    input = 'echo hoge$foo || echo piyo && cat'
    parser = pysh.Parser(pysh.Tokenizer(input))
    ast = parser.parse()
    self.assertEquals(3, len(ast))
    self.assertEquals('&&', ast[0])
    self.assertEquals(3, len(ast[1]))
    self.assertEquals('||', ast[1][0])
    proc0 = ast[1][1]
    self.assertTrue(isinstance(proc0, pysh.Process))
    self.assertEquals([[('literal', 'echo')],
                       [('literal', 'hoge'), ('substitution', '$foo')]],
                      proc0.args)
    self.assertFalse(proc0.redirects)
    proc1 = ast[1][2]
    self.assertTrue(isinstance(proc1, pysh.Process))
    self.assertEquals([[('literal', 'echo')], [('literal', 'piyo')]],
                      proc1.args)
    self.assertFalse(proc1.redirects)
    proc2 = ast[2]
    self.assertTrue(isinstance(proc2, pysh.Process))
    self.assertEquals([[('literal', 'cat')]], proc2.args)
    self.assertFalse(proc2.redirects)

  def testSemicolon(self):
    input = 'echo; cat;'
    parser = pysh.Parser(pysh.Tokenizer(input))
    ast = parser.parse()
    self.assertEquals(3, len(ast))
    self.assertEquals(';', ast[0])
    self.assertTrue(isinstance(ast[1], pysh.Process))
    self.assertTrue(isinstance(ast[2], pysh.Process))

  def testBackquote(self):
    input = 'echo `echo foo`'
    parser = pysh.Parser(pysh.Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, pysh.Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertTrue(isinstance(ast.args[1][0][1], pysh.Process))
    self.assertEquals([[(LITERAL, 'echo')], [(LITERAL, 'foo')]],
                      ast.args[1][0][1].args)


  def testBackquoteWithSpace(self):
    input = 'echo ` echo foo `'
    parser = pysh.Parser(pysh.Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, pysh.Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertTrue(isinstance(ast.args[1][0][1], pysh.Process))
    self.assertEquals([[(LITERAL, 'echo')], [(LITERAL, 'foo')]],
                      ast.args[1][0][1].args)

  def testBackquoteWithSemicolon(self):
    input = 'echo `echo foo;`'
    parser = pysh.Parser(pysh.Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, pysh.Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertTrue(isinstance(ast.args[1][0][1], pysh.Process))
    self.assertEquals([[(LITERAL, 'echo')], [(LITERAL, 'foo')]],
                      ast.args[1][0][1].args)

  def testBackquoteWithSemicolon(self):
    input = 'echo `echo foo | cat`'
    parser = pysh.Parser(pysh.Tokenizer(input))
    ast = parser.parse()
    self.assertTrue(isinstance(ast, pysh.Process))
    self.assertEquals(2, len(ast.args))
    self.assertEquals(1, len(ast.args[1]))
    self.assertEquals(BACKQUOTE, ast.args[1][0][0])
    self.assertEquals('|', ast.args[1][0][1][0])


class EvalTest(unittest.TestCase):
  def getAst(self, cmd):
    tok = pysh.Tokenizer(cmd)
    parser = pysh.Parser(tok)
    return parser.parse()

  def testConditionInPipe(self):
    evalator = pysh.Evaluator(None)
    ast = self.getAst('((foo || bar) && baz) | qux')
    procs = []
    evalator.evalAst(ast, [], procs)
    self.assertEquals(2, len(procs))
    self.assertTrue('foo', procs[0][0].args[0])
    dependency_stack = procs[0][1]
    self.assertEquals(2, len(dependency_stack))
    self.assertTrue('||', dependency_stack[0][0])
    self.assertTrue('&&', dependency_stack[0][1])
    self.assertTrue('qux', procs[1][0].args[0])

  def testPipeInCondition(self):
    evalator = pysh.Evaluator(None)
    ast = self.getAst('((foo || bar) | baz) && qux')
    procs = []
    evalator.evalAst(ast, [], procs)
    self.assertEquals(2, len(procs))

    self.assertTrue('foo', procs[0][0].args[0])
    dependency_stack = procs[0][1]
    self.assertEquals(1, len(dependency_stack))
    self.assertTrue('||', dependency_stack[0][0])

    self.assertTrue('baz', procs[1][0].args[0])
    dependency_stack = procs[1][1]
    self.assertEquals(1, len(dependency_stack))
    self.assertTrue('&&', dependency_stack[0][0])

  def testLeftArrow(self):
    ast = self.getAst('rc <- echo foo | cat')
    self.assertEquals(3, len(ast))
    self.assertEquals('<-', ast[0])
    self.assertEquals('rc', ast[1])
    self.assertEquals('|', ast[2][0])

  def testLeftArrowInParenthesis(self):
    ast = self.getAst('(rc <- echo foo) | cat')
    self.assertEquals(3, len(ast))
    self.assertEquals('|', ast[0])
    ast = ast[1]
    self.assertEquals(3, len(ast))
    self.assertEquals('<-', ast[0])
    self.assertEquals('rc', ast[1])

  def testRightArrow(self):
    ast = self.getAst('echo foo -> rc')
    self.assertEquals(3, len(ast))
    self.assertEquals('->', ast[0])
    self.assertTrue(isinstance(ast[1], pysh.Process))
    self.assertEquals('rc', ast[2])

  def testBoldRightArrow(self):
    ast = self.getAst('echo foo => out')
    self.assertEquals(1, len(ast.redirects))
    self.assertEquals(('=>', 'out'), ast.redirects[0])


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
    pysh.run('echo foo bar > out.txt', globals(), locals())
    self.assertEquals('foo bar\n', file('out.txt').read())

  def testAppendRedirect(self):
    pysh.run('echo foo > out.txt', globals(), locals())
    pysh.run('echo bar >> out.txt', globals(), locals())
    self.assertEquals('foo\nbar\n', file('out.txt').read())

  def testPipe(self):
    file('tmp.txt', 'w').write('a\nb\nc\n')
    pysh.run('cat tmp.txt | grep -v b > out.txt', globals(), locals())
    self.assertEquals('a\nc\n', file('out.txt').read())

  def testVar(self):
    message = 'Hello world.'
    pysh.run('echo $message > out.txt', globals(), locals())
    self.assertEquals('Hello world.\n', file('out.txt').read())

  def testGlobalVar(self):
    pysh.run('echo $__name__ > out.txt', globals(), locals())
    self.assertEquals('__main__\n', file('out.txt').read())

  def testBuiltinVar(self):
    map_str = str(map)
    pysh.run('echo $map > out.txt', globals(), locals())
    self.assertEquals(map_str + '\n', file('out.txt').read())

  def testExpression(self):
    map_str = str(map)
    pysh.run('echo ${{len("abc") :[3 * 4 + 10]}} > out.txt',
             globals(), locals())
    self.assertEquals('{3: [22]}\n', file('out.txt').read())

  def testListComprehension(self):
    pysh.run('send ${[x * x for x in xrange(3)]} > out.txt',
             globals(), locals())
    self.assertEquals('0\n1\n4\n', file('out.txt').read())

  def testEnvVar(self):
    os.environ['YUNABE_PYSH_TEST_VAR'] = 'foobarbaz'
    pysh.run('echo $YUNABE_PYSH_TEST_VAR > out.txt', globals(), locals())
    self.assertEquals('foobarbaz\n', file('out.txt').read())

  def testStringArgs(self):
    pysh.run('python -c "import sys;print sys.argv" '
             '"a b" \'c d\' e f > out.txt', globals(), locals())
    argv = eval(file('out.txt').read())
    self.assertEquals(['-c', 'a b', 'c d', 'e', 'f'], argv)

  def testListArgs(self):
    args = ['a', 'b', 10, {1: 3}]
    pysh.run('python -c "import sys;print sys.argv" '
             '$args > out.txt', globals(), locals())
    argv = eval(file('out.txt').read())
    self.assertEquals(['-c', 'a', 'b', '10', '{1: 3}'], argv)

  def testNumberedRedirect(self):
    pysh.run('python -c "import sys;'
             'print >> sys.stderr, \'error\';print \'out\'"'
             '> stdout.txt 2> stderr.txt',
             globals(), locals())
    self.assertEquals('error\n', file('stderr.txt').read())
    self.assertEquals('out\n', file('stdout.txt').read())

  def testDivertRedirect(self):
    pysh.run('python -c "import sys;'
             'print >> sys.stderr, \'error\';print \'out\'"'
             '>out.txt 2>&1', globals(), locals())
    self.assertEquals('error\nout\n', file('out.txt').read())

  def testPyCmd(self):
    pysh.run('echo "foo\\nbar" | pycmd a b c | cat > out.txt',
             globals(), locals())
    self.assertEquals('pycmd\na\nb\nc\nfoo\nbar\n', file('out.txt').read())

  def testPyCmdRedirect(self):
    pysh.run('echo "foo" | pycmd a b c > out.txt',
             globals(), locals())
    self.assertEquals('pycmd\na\nb\nc\nfoo\n', file('out.txt').read())

  def testPyCmdSequence(self):
    pysh.run('echo "foo" | pycmd bar | pycmd baz | cat > out.txt',
             globals(), locals())
    self.assertEquals('pycmd\nbaz\npycmd\nbar\nfoo\n', file('out.txt').read())

  def testPyCmdInVar(self):
    class Tmp(object):
      def process(self, args, input):
        return ['tmp', 19]
    tmp = Tmp()
    pysh.run('$tmp > out.txt', globals(), locals())
    self.assertEquals('tmp\n19\n', file('out.txt').read())

  def testReceiveData(self):
    out = []
    pysh.run('echo "foo\\nbar" | recv $out', globals(), locals())
    self.assertEquals(['foo', 'bar'], out)

  def testSendData(self):
    data = ['foo', 'bar', 'baz']
    pysh.run('send $data | sort > out.txt', globals(), locals())
    self.assertEquals('bar\nbaz\nfoo\n', file('out.txt').read())

  def testMapCmd(self):
    pysh.run('echo "1\\n2\\n3\\n4\\n5" | map ${lambda l: int(l)} |'
             'map ${lambda x: x * x} > out.txt', globals(), locals())
    self.assertEquals('1\n4\n9\n16\n25\n', file('out.txt').read())

  def testFilterCmd(self):
    pysh.run('echo "cupcake\\ndonut\\nfroyo\\nginger" |'
             'filter ${lambda l: "e" in l} > out.txt',
             globals(), locals())
    self.assertEquals('cupcake\nginger\n', file('out.txt').read())

  def testReduceCmd(self):
    pysh.run('echo "foo\\nbar" | reduce ${lambda x, y: x + y} |'
             'cat > out.txt', globals(), locals())
    self.assertEquals('foobar\n', file('out.txt').read())

  def testReadCvsCmd(self):
    pysh.run('echo \'a,b,"c,"\' > in.txt', globals(), locals())
    pysh.run('echo \'e,"f","""g"""\' >> in.txt', globals(), locals())
    pysh.run('cat in.txt | readcsv |'
             'map ${lambda row: row[2]} > out.txt',
             globals(), locals())
    self.assertEquals('c,\n"g"\n', file('out.txt').read())

  def testAnd(self):
    pysh.run('echo hoge >> out.txt && echo piyo >> out.txt',
             globals(), locals())
    self.assertEquals('hoge\npiyo\n', file('out.txt').read())

  def testOr(self):
    pysh.run('echo hoge >> out.txt || echo piyo >> out.txt',
             globals(), locals())
    self.assertEquals('hoge\n', file('out.txt').read())

  def testOrAnd(self):
    pysh.run('(echo foo >> out.txt || echo bar >> out.txt) && '
             'echo baz >> out.txt', globals(), locals())
    self.assertEquals('foo\nbaz\n', file('out.txt').read())

  def testAndOr(self):
    pysh.run('(python -c "import sys;sys.exit(1)" >> out.txt && echo bar) || '
             'echo baz >> out.txt)', globals(), locals())
    self.assertEquals('baz\n', file('out.txt').read())

  def testAndNot(self):
    pysh.run('python -c "import sys;sys.exit(1)" > out.txt && '
             'echo foo >> out.txt', globals(), locals())
    self.assertEquals('', file('out.txt').read())

  def testOrNot(self):
    pysh.run('python -c "import sys;sys.exit(1)" > out.txt || '
             'echo foo >> out.txt', globals(), locals())
    self.assertEquals('foo\n', file('out.txt').read())

  def testAndPyCmd(self):
    class Tmp(object):
      def process(self, args, input):
        return ['tmp']
    tmp = Tmp()
    pysh.run('$tmp > out.txt && echo foo >> out.txt', globals(), locals())
    self.assertEquals('tmp\nfoo\n', file('out.txt').read())

  def testOrPyCmd(self):
    class Tmp(object):
      def process(self, args, input):
        return ['tmp']
    tmp = Tmp()
    pysh.run('$tmp > out.txt || echo foo >> out.txt', globals(), locals())
    self.assertEquals('tmp\n', file('out.txt').read())

  def testAndNotPyCmd(self):
    class Tmp(object):
      def process(self, args, input):
        raise Exception('Error!')
    tmp = Tmp()
    pysh.run('$tmp > out.txt && echo foo >> out.txt', globals(), locals())
    self.assertEquals('', file('out.txt').read())

  def testOrNotPyCmd(self):
    class Tmp(object):
      def process(self, args, input):
        raise Exception('Error!')
    tmp = Tmp()
    pysh.run('$tmp > out.txt || echo foo >> out.txt', globals(), locals())
    self.assertEquals('foo\n', file('out.txt').read())

  def testReturnCodeLeft(self):
    rc = pysh.run('rc <- echo foo >> /dev/null', globals(), locals())
    self.assertEquals(1, len(rc))
    self.assertEquals(0, rc['rc'])

  def testReturnCodeMultiLeft(self):
    rc = pysh.run('(rc0 <- echo foo >> /dev/null) && '
                  '(rc1 <- echo bar >> /dev/null)', globals(), locals())
    self.assertEquals(2, len(rc))
    self.assertEquals(0, rc['rc0'])
    self.assertEquals(0, rc['rc1'])

  def testReturnCode(self):
    rc = pysh.run('python -c "import sys;sys.exit(7)" -> rc',
                  globals(), locals())
    self.assertEquals(1, len(rc))
    self.assertEquals(True, os.WIFEXITED(rc['rc']))
    self.assertEquals(7, os.WEXITSTATUS(rc['rc']))

  def testReturnCodeMulti(self):
    rc = pysh.run('(echo foo >> /dev/null -> rc0) && '
                  '(echo bar >> /dev/null -> rc1)', globals(), locals())
    self.assertEquals(2, len(rc))
    self.assertEquals(0, rc['rc0'])
    self.assertEquals(0, rc['rc1'])

  def testSemiColon(self):
    rc = pysh.run('echo foo >> out.txt; echo bar >> out.txt',
                  globals(), locals())
    self.assertEquals('foo\nbar\n', file('out.txt').read())

  def testExpandUser(self):
    rc = pysh.run('echo ~/test.txt > out.txt', globals(), locals())
    path = os.path.expanduser('~/test.txt')
    self.assertEquals(path + '\n', file('out.txt').read())

  def testChangeDir(self):
    rc = pysh.run('cd /dev', globals(), locals())
    self.assertEquals('/dev', os.getcwd())

  def testGlob(self):
    pysh.run('echo foo > foo.txt', globals(), locals())
    pysh.run('echo bar > bar.txt', globals(), locals())
    pysh.run('echo baz > baz.doc', globals(), locals())
    pysh.run('echo test > "a*b.doc"', globals(), locals())
    pysh.run('echo *.txt > out1.txt', globals(), locals())
    pysh.run('echo "*.txt" > out2.txt', globals(), locals())
    pysh.run('echo *\'*\'*.doc > out3.txt', globals(), locals())
    self.assertEquals('bar.txt foo.txt\n', file('out1.txt').read())
    self.assertEquals('*.txt\n', file('out2.txt').read())
    self.assertEquals('a*b.doc\n', file('out3.txt').read())

if __name__ == '__main__':
  unittest.main()
