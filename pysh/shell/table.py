
class Table(object):
    def __init__(self, cols):
        self.__cols = cols
        self.__rows = []
        self.__col_index = {}
        for i, col in enumerate(cols):
            self.__col_index[col] = i

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


    def where(self, cond):
        new = Table(self.__cols)
        for row in self.__rows:
            if eval(cond, None, row):
                new.add_row(row.values())
        return new

    def orderby(self, order):
        orders = []
        for i, row in enumerate(self.__rows):
            orders.append((eval(order, None, row), i))
        orders.sort()
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

