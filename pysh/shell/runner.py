import pysh.shell.builtin
import pysh.shell.evaluator

def run(cmd_str, globals, locals, responses=None, alias_map=None):
  rc = pysh.shell.evaluator.run(cmd_str, globals, locals, alias_map)
  if not responses:
    return None
  result = []
  for response in responses:
    result.append(rc[response] if response in rc else None)
  return tuple(result)
