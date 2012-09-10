import os
import re
import sys
import StringIO

from pysh.converter import Converter, RoughLexer
from pysh.shell.tokenizer import Tokenizer
from pysh.shell.parser import Parser
from pysh.shell.parser import Process


def usage_exit():
  print >> sys.stderr, 'Usage: pysh [-c cmd | file | -]'
  sys.exit(1)


def main():
  if len(sys.argv) < 2:
    usage_exit()
  if sys.argv[1] == '-':
    reader = sys.stdin
    writer = StringIO.StringIO()
    Converter(RoughLexer(reader), writer).convert(False)
    argv = sys.argv[2:]
    os.execlp('python', 'python', '-c', writer.getvalue(), *argv)
  elif sys.argv[1] == '-c':
    if len(sys.argv) < 3:
      usage_exit()
    reader = StringIO.StringIO(sys.argv[2])
    writer = StringIO.StringIO()
    Converter(RoughLexer(reader), writer).convert(False)
    argv = sys.argv[3:]
    os.execlp('python', 'python', '-c', writer.getvalue(), *argv)
  else:
    script = sys.argv[1]
    name, ext = os.path.splitext(script)
    if ext == ".py":
      print >> sys.stderr, 'An input file shoundn\'t be *.py.'
      sys.exit(1)
    py = name + '.py'
    reader = file(script, 'r')
    writer = file(py, 'w')
    Converter(RoughLexer(reader), writer).convert(True)
    writer.close()
    argv = sys.argv[2:]
    os.execlp('python', 'python', py, *argv)


if __name__ == '__main__':
  main()
