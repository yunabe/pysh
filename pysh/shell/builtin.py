import collections
import csv
import os
import StringIO

from pysh.shell.pycmd import register_pycmd
from pysh.shell.pycmd import pycmd
from pysh.shell.pycmd import IOType


def file_to_array(f):
  return map(lambda line: line.rstrip('\r\n'), f.readlines())


@pycmd(name='echo', inType=IOType.No)
def pycmd_echo(args, input):
  line = []
  for arg in args[1:]:
    if not isinstance(arg, basestring) and (
      isinstance(arg, collections.Iterable)):
      if line:
        yield ' '.join(line)
        line = []
      for e in arg:
        yield e
    else:
      line.append(str(arg))
  if line:
    yield ' '.join(line)


@pycmd(name='map')
def pycmd_map(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return (f(x) for x in input)


@pycmd(name='filter')
def pycmd_filter(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  cond = args[1]
  assert callable(cond)
  for x in input:
    if cond(x):
      yield x


@pycmd(name='reduce')
def pycmd_reduce(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return [reduce(f, input)]


@pycmd(name='readcsv')
def pycmd_readcsv(args, input):
  return csv.reader(input)


@pycmd(name='cd', inType=IOType.No, outType=IOType.No)
def pycmd_cd(args, input):
  assert len(args) == 2 or len(args) == 1
  if len(args) == 2:
    dir = args[1]
  else:
    dir = os.environ.get('HOME', '')
  if dir:
    os.chdir(dir)
  return ()
