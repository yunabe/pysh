import StringIO
import unittest

from pysh.converter import RoughLexer
from pysh.converter import Converter

class RoughLexerTest(unittest.TestCase):
  def testSimplePython(self):
    reader = StringIO.StringIO('print 3 + 4')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print 3 + 4')], list(lexer))

  def testSimplePython(self):
    reader = StringIO.StringIO('print 3 + 4\\\n + 5')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print 3 + 4 + 5')], list(lexer))

  def testSimpleShell(self):
    reader = StringIO.StringIO('> echo foo\\\n bar')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'shell', 'echo foo bar')], list(lexer))

  def testString(self):
    reader = StringIO.StringIO('print "apple"\nprint \'banana\'')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print "apple"'),
                       ('', 'python', 'print \'banana\'')], list(lexer))

  def testEscapeInString(self):
    content = '"apple\\"tbanana" \'cake\\\'donuts\''
    reader = StringIO.StringIO(content)
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', content)], list(lexer))

  def testBackslashInString(self):
    content = '"apple\\\nbanana"'
    reader = StringIO.StringIO(content)
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', '"applebanana"')], list(lexer))

  def testHereDocument(self):
    reader = StringIO.StringIO('print """apple"""\nprint \'\'\'banana\'\'\'')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print """apple"""'),
                       ('', 'python', 'print \'\'\'banana\'\'\'')], list(lexer))

  def testHereDocument(self):
    reader = StringIO.StringIO('print """apple"""\nprint \'\'\'banana\'\'\'')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print """apple"""'),
                       ('', 'python', 'print \'\'\'banana\'\'\'')], list(lexer))

  def testEscapeHereDocument(self):
    reader = StringIO.StringIO('print """\\""""')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print """\\""""')], list(lexer))

  def testBackslashInHereDocument(self):
    content = '"""apple\\\nbanana"""'
    reader = StringIO.StringIO(content)
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', '"""applebanana"""')], list(lexer))

  def testComment(self):
    reader = StringIO.StringIO('print 10 # comment')
    lexer = RoughLexer(reader)
    self.assertEquals([('', 'python', 'print 10 ')], list(lexer))


class RecordPredictionLexer(RoughLexer):
  def __init__(self, reader, log):
    RoughLexer.__init__(self, reader)
    self.__log = log

  def _predict_indent(self, indent):
    self.__log.append(indent)


class IndentPredictionTest(unittest.TestCase):
  def testNoIndent(self):
    reader = StringIO.StringIO('print 3 + 4\n  print 4 + 5')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    lexer.next()
    lexer.next()
    self.assertEquals(['', '  '], log)

  def testIfStmt(self):
    reader = StringIO.StringIO('if x:\n')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    lexer.next()
    self.assertEquals([' ' * 4], log)

  def testIfStmtWithIndent(self):
    reader = StringIO.StringIO('  if x:\n')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    lexer.next()
    self.assertEquals([' ' * 6], log)

  def testUnindentWithBlankline(self):
    reader = StringIO.StringIO('  if x:\n    f(x)\n         \n')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    list(lexer)
    self.assertEquals([' ' * 6, ' ' * 4, ' ' * 2], log)


  def testPass(self):
    reader = StringIO.StringIO('if x:\n  pass\n')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    lexer.next()
    lexer.next()
    self.assertEquals([' ' * 4, ''], log)

  def testPassWithIndent(self):
    reader = StringIO.StringIO('  if x:\n    pass\n')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    lexer.next()
    lexer.next()
    self.assertEquals([' ' * 6, '  '], log)

  def testReturn(self):
    reader = StringIO.StringIO('if x:\n  return f(x)\n')
    log = []
    lexer = RecordPredictionLexer(reader, log)
    lexer.next()
    lexer.next()
    self.assertEquals([' ' * 4, ''], log)


class ConverterTest(unittest.TestCase):
  def testExtractResponseNames(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames('echo foo -> bar')
    self.assertEquals(['bar'], names)

  def testExtractResponseNames_Redirection(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames('echo foo => bar')
    self.assertEquals(['bar'], names)

  def testExtractResponseNames_InBinaryOp(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames('echo foo -> bar && echo baz => qux')
    self.assertEquals(['bar', 'qux'], names)

  def testExtractResponseNames_InAssignCmd(self):
    converter = Converter(None, None)
    names = converter.extractResponseNames(
      '(echo foo -> bar && echo baz => qux) -> piyo')
    self.assertEquals(['bar', 'qux', 'piyo'], names)


if __name__ == '__main__':
  unittest.main()
