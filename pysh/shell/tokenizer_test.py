
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

from pysh.shell.tokenizer import Tokenizer
from pysh.shell.tokenizer import RegexMather

import re
import shutil
import tempfile
import unittest

class RegexMatherTest(unittest.TestCase):
  def test(self):
    pattern = re.compile(r'abc')
    matcher = RegexMather(pattern, LITERAL)

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
    tok = Tokenizer('cat /tmp/www/foo.txt')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def test1(self):
    tok = Tokenizer('cat        /tmp/www/foo.txt')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def test2(self):
    tok = Tokenizer(' cat /tmp/www/foo.txt ')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def test2_2(self):
    tok = Tokenizer('cat\t/tmp/www/foo.txt')
    self.assertEquals([(LITERAL, 'cat'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitution(self):
    tok = Tokenizer('echo $a$b/$c')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '$a'),
                       (SUBSTITUTION, '$b'),
                       (LITERAL, '/'),
                       (SUBSTITUTION, '$c'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionWithSpace(self):
    tok = Tokenizer('echo $a $b /$c')
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
    tok = Tokenizer('echo hoge$a')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'hoge'),
                       (SUBSTITUTION, '$a'),
                       (EOF, ''),
                       ], list(tok))

  def testBraceSubstitution(self):
    tok = Tokenizer('echo hoge${a}')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'hoge'),
                       (SUBSTITUTION, '${a}'),
                       (EOF, ''),
                       ], list(tok))

  def testBraceSubstitutionWithTrailing(self):
    tok = Tokenizer('echo hoge${a}10')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'hoge'),
                       (SUBSTITUTION, '${a}'),
                       (LITERAL, '10'),
                       (EOF, ''),
                       ], list(tok))

  def testExpression(self):
    tok = Tokenizer('echo ${{1: 10}}')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '${{1: 10}}'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionUnderscore(self):
    tok = Tokenizer('echo $__init__')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SUBSTITUTION, '$__init__'),
                       (EOF, ''),
                       ], list(tok))

  def testPipe(self):
    tok = Tokenizer('cat | /tmp/out')
    self.assertEquals([(LITERAL, 'cat'),
                       (PIPE, '|'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))

  def testPipeWithoutSpace(self):
    tok = Tokenizer('cat|/tmp/out')
    self.assertEquals([(LITERAL, 'cat'),
                       (PIPE, '|'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))


  def testRedirect(self):
    tok = Tokenizer('echo a>/tmp/out')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'a'),
                       (REDIRECT, '>'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))

  def testRedirectAppend(self):
    tok = Tokenizer('echo a>>/tmp/out')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'a'),
                       (REDIRECT, '>>'),
                       (LITERAL, '/tmp/out'),
                       (EOF, ''),
                       ], list(tok))

  def testRedirectInvalidName(self):
    tok = Tokenizer('echo $10')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, '$'),
                       (LITERAL, '10'),
                       (EOF, ''),
                       ], list(tok))

  def testRedirectAppend(self):
    tok = Tokenizer('echo \'abc\'"def"')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (SINGLE_QUOTED_STRING, '\'abc\''),
                       (DOUBLE_QUOTED_STRING, '"def"'),
                       (EOF, ''),
                       ], list(tok))

  def testAndOrOperator(self):
    tok = Tokenizer('foo && bar || a&&b||c')
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
    tok = Tokenizer('() a(b)')
    self.assertEquals([(PARENTHESIS_START, '('),
                       (PARENTHESIS_END, ')'),
                       (LITERAL, 'a'),
                       (PARENTHESIS_START, '('),
                       (LITERAL, 'b'),
                       (PARENTHESIS_END, ')'),
                       (EOF, '')], list(tok))

  def testRightArrow(self):
    tok = Tokenizer('echo->x')
    self.assertEquals([(LITERAL, 'echo'),
                       (RIGHT_ARROW, '->'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))
    tok = Tokenizer('echo -> x')
    self.assertEquals([(LITERAL, 'echo'),
                       (RIGHT_ARROW, '->'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))

  def testBoldRightArrow(self):
    tok = Tokenizer('echo=>x')
    self.assertEquals([(LITERAL, 'echo'),
                       (BOLD_RIGHT_ARROW, '=>'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))
    tok = Tokenizer('echo => x')
    self.assertEquals([(LITERAL, 'echo'),
                       (BOLD_RIGHT_ARROW, '=>'),
                       (LITERAL, 'x'),
                       (EOF, '')], list(tok))

  def testHyphenEqualInLiteral(self):
    tok = Tokenizer('echo x- -- -')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'x-'),
                       (SPACE, ' '),
                       (LITERAL, '--'),
                       (SPACE, ' '),
                       (LITERAL, '-'),
                       (EOF, '')], list(tok))
    tok = Tokenizer('echo x= == =')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'x='),
                       (SPACE, ' '),
                       (LITERAL, '=='),
                       (SPACE, ' '),
                       (LITERAL, '='),
                       (EOF, '')], list(tok))

  def testSemicolon(self):
    tok = Tokenizer('a;b;')
    self.assertEquals([(LITERAL, 'a'),
                       (SEMICOLON, ';'),
                       (LITERAL, 'b'),
                       (SEMICOLON, ';'),
                       (EOF, '')], list(tok))

  def testSemicolonWithSpace(self):
    tok = Tokenizer('a ; b ; ')
    self.assertEquals([(LITERAL, 'a'),
                       (SEMICOLON, ';'),
                       (LITERAL, 'b'),
                       (SEMICOLON, ';'),
                       (EOF, '')], list(tok))

  def testBackQuote(self):
    tok = Tokenizer('echo `echo foo`')
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (BACKQUOTE, '`'),
                       (LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'foo'),
                       (BACKQUOTE, '`'),
                       (EOF, '')], list(tok))

  def testBackQuoteWithSpace(self):
    tok = Tokenizer('echo ` echo foo `')
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
    tok = Tokenizer('ls /tmp/www/foo.txt', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (SPACE, ' '),
                       (LITERAL, '-la'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def testNotGlobal(self):
    alias_map = {'ls': ('ls -la', False)}
    tok = Tokenizer('echo ls /tmp/www/foo.txt', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'ls'),
                       (SPACE, ' '),
                       (LITERAL, '/tmp/www/foo.txt'),
                       (EOF, ''),
                       ], list(tok))

  def testGlobal(self):
    alias_map = {'GR': ('| grep &&', True)}
    tok = Tokenizer('ls GR echo', alias_map=alias_map)
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
    tok = Tokenizer('sl', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (SPACE, ' '),
                       (LITERAL, '-la'),
                       (EOF, ''),
                       ], list(tok))

  def testRecursiveNotGlobal(self):
    alias_map = {'ls': ('ls -la', False),
                 'sl': ('ls', True)}
    tok = Tokenizer('echo sl', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'echo'),
                       (SPACE, ' '),
                       (LITERAL, 'ls'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionSuffix(self):
    alias_map = {'ls': ('ls -la', False)}
    tok = Tokenizer('ls$x', alias_map=alias_map)
    self.assertEquals([(LITERAL, 'ls'),
                       (SUBSTITUTION, '$x'),
                       (EOF, ''),
                       ], list(tok))

  def testSubstitutionPrefix(self):
    alias_map = {'GR': ('| grep', True)}
    tok = Tokenizer('${x}GR', alias_map=alias_map)
    self.assertEquals([(SUBSTITUTION, '${x}'),
                       (LITERAL, 'GR'),
                       (EOF, ''),
                       ], list(tok))


if __name__ == '__main__':
  unittest.main()
