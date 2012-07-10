from __future__ import absolute_import

import parser
import re
import tokenize
import token
import StringIO

SPACE = 'space'
SINGLE_QUOTED_STRING = 'single_quoted'
DOUBLE_QUOTED_STRING = 'double_quoted'
SUBSTITUTION = 'substitution'
REDIRECT = 'redirect'
PIPE = 'pipe'
RIGHT_ARROW = 'right_arrow'
BOLD_RIGHT_ARROW = 'bright_arrow'
LITERAL = 'literal'
AND_OP = 'andop'
OR_OP = 'orop'
PARENTHESIS_START = 'parenthesis_start'
PARENTHESIS_END = 'parenthesis_end'
SEMICOLON = 'semicolon'
BACKQUOTE = 'bquote'
EOF = 'eof'

SPACE_SENSITIVE = set((SINGLE_QUOTED_STRING, DOUBLE_QUOTED_STRING,
                       SUBSTITUTION, LITERAL, BACKQUOTE))

REDIRECT_PATTERN = re.compile(r'(\d*)>(>)?(?:&(\d+))?')
SPACE_PATTERN = re.compile(r'[ \t]+')
VARIABLE_PATTERN = re.compile(r'\$[_a-zA-Z][_a-zA-Z0-9]*')
PIPE_PATTERN = re.compile(r'\|')
RIGHT_ARROW_PATTERN = re.compile(r'\->')
BOLD_RIGHT_ARROW_PATTERN = re.compile(r'\=>')
SINGLE_DOLLAR_PATTERN = re.compile(r'\$')
AND_OPERATOR_PATTERN = re.compile(r'&&')
PARENTHESIS_START_PATTERN = re.compile(r'\(')
PARENTHESIS_END_PATTERN = re.compile(r'\)')
OR_OPERATOR_PATTERN = re.compile(r'\|\|')
SEMICOLON_PATTERN = re.compile(r';')
BACKQUOTE_PATTERN = re.compile(r'`')
LITERAL_PATTERN = re.compile(r'([0-9A-Za-z\!\#\%\*\+\,\.\/\:'
                             r'\?\@\[\\\]\^\_\{\}\~]'
                             r'|\-(?!>)|\=(?!>))+')


class RegexMather(object):
  def __init__(self, regex, type):
    self.__pattern = re.compile(regex)
    self.__type = type

  def consume(self, input):
    match = self.__pattern.match(input) 
    if not match:
      return None, None, 0
    string = match.group(0)
    consumed = len(string)
    input = input[consumed:]
    return self.__type, string, consumed


class StringMatcher(object):
  def consume(self, input):
    type = None
    if input.startswith('"'):
      type = DOUBLE_QUOTED_STRING
    elif input.startswith('\''):
      type = SINGLE_QUOTED_STRING

    if type is not None:
      toks = tokenize.generate_tokens(StringIO.StringIO(input).readline)
      tok = toks.next()
      if tok[0] == token.STRING:
        return type, tok[1], len(tok[1])
      else:
        raise Exception('Wrong string format')
    else:
      return None, None, 0


class ExprMatcher(object):
  def consume(self, input):
    if not input.startswith('${'):
      return None, None, 0
    input = input[2:]
    try:
      parser.expr(input)
      raise Exception('Expected } but EOF found.')
    except SyntaxError, e:
      if input[e.offset - 1] != '}':
        raise
    expr = input[:e.offset - 1]
    parser.expr(expr)
    string = '${%s}' % expr
    return SUBSTITUTION, string, len(string)

class Tokenizer(object):
  def __init__(self, input,
               global_alias_only=False, alias_map=None, alias_history=None):
    self.cur = None
    self.__next = None
    self.__input = input.strip()
    self.__global_alias_only = global_alias_only
    self.__tokens = []
    self.__alias_map = alias_map
    self.__eof = False
    self.__alias_history = alias_history or set()
    self.__matchers = [
      RegexMather(REDIRECT_PATTERN, REDIRECT),
      RegexMather(AND_OPERATOR_PATTERN, AND_OP),
      # should precede PIPE_PATTERN
      RegexMather(OR_OPERATOR_PATTERN, OR_OP),
      RegexMather(PIPE_PATTERN, PIPE),
      RegexMather(RIGHT_ARROW_PATTERN, RIGHT_ARROW),
      RegexMather(BOLD_RIGHT_ARROW_PATTERN, BOLD_RIGHT_ARROW),
      RegexMather(PARENTHESIS_START_PATTERN, PARENTHESIS_START),
      RegexMather(PARENTHESIS_END_PATTERN, PARENTHESIS_END),
      RegexMather(SEMICOLON_PATTERN, SEMICOLON),
      RegexMather(BACKQUOTE_PATTERN, BACKQUOTE),
      StringMatcher(),
      RegexMather(VARIABLE_PATTERN, SUBSTITUTION),
      ExprMatcher(),
      RegexMather(SINGLE_DOLLAR_PATTERN, LITERAL),
      RegexMather(SPACE_PATTERN, SPACE),
      RegexMather(LITERAL_PATTERN, LITERAL),
      ]

  def __iter__(self):
    return self

  def next(self):
    if not self.cur:
      self.cur = self.__get_next()
    else:
      if self.cur[0] == EOF:
        raise StopIteration()
      self.cur = self.__next
      self.__next = None
    if self.cur and self.cur[0] == EOF:
      return self.cur

    self.__next = self.__get_next()
    while True:
      # skip space toke if it's unnecessary.
      # Please note that we call break if self.__next is EOF.
      if self.__next[0] == SPACE and not self.cur[0] in SPACE_SENSITIVE:
        self.__next = self.__get_next()
      elif self.cur[0] == SPACE and not self.__next[0] in SPACE_SENSITIVE:
        self.cur = self.__next
        self.__next = self.__get_next()
      else:
        break
    return self.cur

  def __get_next(self):
    if self.__tokens:
      next = self.__tokens[0]
      self.__tokens = self.__tokens[1:]
    else:
      next = self.__next_exalias()
    self.__global_alias_only = True
    return next

  def __is_literal_like(self, tok):
    return (tok[0] == LITERAL or tok[0] == SINGLE_QUOTED_STRING or
            tok[0] == DOUBLE_QUOTED_STRING or tok[0] == SUBSTITUTION)

  def __next_exalias(self):
    # If tok is literal, try to expand alias.
    tok = self.__next_internal()
    if tok[0] != LITERAL or (self.cur and self.__is_literal_like(self.cur)):
      return tok

    next = self.__next_internal()
    if self.__is_literal_like(next):
      self.__tokens.append(next)
      return tok

    expanded = self.__expand_alias(tok[1])
    if expanded:
      self.__tokens.extend(expanded[1:])
      self.__tokens.append(next)
      return expanded[0]
    else:
      return next

  def __expand_alias(self, text):
    if (not self.__alias_map or text in self.__alias_history or
        not text in self.__alias_map):
      return [(LITERAL, text)]

    alias, is_global = self.__alias_map[text]
    if self.__global_alias_only and not is_global:
      return [(LITERAL, text)]
    self.__alias_history.add(text)
    alias_tokenizer = Tokenizer(alias,
                                global_alias_only=self.__global_alias_only,
                                alias_map=self.__alias_map,
                                alias_history=self.__alias_history)
    # strip eof
    result = list(alias_tokenizer)[:-1]
    self.__alias_history.remove(text)
    return result

  def __next_internal(self):
    input = self.__input
    if not input:
      if self.__eof:
        raise StopIteration()
      else:
        self.__eof = True
        return EOF, ''

    for matcher in self.__matchers:
      token, string, consumed = matcher.consume(input)
      if token is not None:
        self.__input = self.__input[consumed:]
        if token == SPACE:
          return token, ' '
        else:
          return token, string

    raise Exception('Failed to tokenize: ' + self.__input[:100])
