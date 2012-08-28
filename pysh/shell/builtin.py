import collections
import csv
import os
import StringIO

from pysh.shell.pycmd import register_pycmd


def file_to_array(f):
  return map(lambda line: line.rstrip('\r\n'), f.readlines())


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


def pycmd_map(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return (f(x) for x in input)


def pycmd_filter(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  cond = args[1]
  assert callable(cond)
  for x in input:
    if cond(x):
      yield x


def pycmd_reduce(args, input):
  assert len(args) == 2
  if isinstance(input, file):
    input = file_to_array(input)
  f = args[1]
  assert callable(f)
  return [reduce(f, input)]


def pycmd_readcsv(args, input):
  return csv.reader(input)


def pycmd_cd(args, input):
  assert len(args) == 2 or len(args) == 1
  if len(args) == 2:
    dir = args[1]
  else:
    dir = os.environ.get('HOME', '')
  if dir:
    os.chdir(dir)
  return ()


def register_builtin():
  register_pycmd('echo', pycmd_echo)
  register_pycmd('map', pycmd_map)
  register_pycmd('filter', pycmd_filter)
  register_pycmd('reduce', pycmd_reduce)
  register_pycmd('readcsv', pycmd_readcsv)
  register_pycmd('cd', pycmd_cd)
