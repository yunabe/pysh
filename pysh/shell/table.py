
class VarDict(object):
    def __init__(self, locals, row):
        self.__row = row
        self.__locals = locals

    def __getitem__(self, key):
        if not self.__locals:
            return self.__row[key]
        try:
            return self.__row[key]
        except KeyError:
            return self.__locals[key]

class Table(object):
    def __init__(self, cols):
        self.__cols = cols
        self.__rows = []
        self.__col_index = {}
        for i, col in enumerate(cols):
            self.__col_index[col] = i

    def cols(self):
        return self.__cols

    def __iter__(self):
        return self.__rows.__iter__()

    def add_row(self, values):
        row = Row(self, values)
        self.__rows.append(row)
        return row

    def col_index(self, col):
        return self.__col_index[col]

    def rows(self):
        return self.__rows

    def pretty_print(self, writer, sep=' |'):
        # key -> len(key)
        max_width = dict(zip(self.__cols, map(len, self.__cols)))
        for row in self.__rows:
            for col in self.__cols:
                value = row[col]
                max_width[col] = max(max_width[col], len(str(value)))
        for i, col in enumerate(self.__cols):
            if i != 0:
                writer.write(sep)
            writer.write(('%% %ds' % max_width[col]) % col)
        writer.write('\n')
        writer.write('-' * reduce(lambda x, y: x + y + len(sep),
                                  max_width.values()))
        writer.write('\n')
        for row in self.__rows:
            for i, col in enumerate(self.__cols):
                if i != 0:
                    writer.write(sep)
                writer.write(('%% %ds' % max_width[col]) % str(row[col]))
            writer.write('\n')

    def where(self, cond, globals=None, locals=None):
        new = Table(self.__cols)
        for row in self.__rows:
            if eval(cond, globals, VarDict(locals, row)):
                new.add_row(row.values())
        return new

    def orderby(self, order, asc=True, globals=None, locals=None):
        orders = []
        for i, row in enumerate(self.__rows):
            orders.append((eval(order, globals, VarDict(locals, row)), i))
        if asc:
            comparator = cmp
        else:
            comparator = lambda x, y: cmp(y, x)
        orders.sort(comparator)
        new = Table(self.__cols)
        for _, i in orders:
            new.add_row(self.__rows[i].values())
        return new


class Row(object):
    def __init__(self, table, values):
        self.__table = table
        self.__values = values

    def table(self):
        return self.__table

    def values(self):
        return self.__values

    def __getitem__(self, key):
        return self.__values[self.__table.col_index(key)]

    def __getattr__(self, key):
        return self.__getitem__(key)

    def __setattribute__(self, key, value):
        self.__values[self.__table.col_index(key)] = value

