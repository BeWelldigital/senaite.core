# -*- coding: utf-8 -*-

from collective.z3cform.datagridfield.interfaces import IDataGridField
from z3c.form.interfaces import IObjectWidget
from z3c.form.interfaces import IWidget


class INumberWidget(IWidget):
    """Input type "number" widget
    """


class IDataGridWidget(IDataGridField):
    """Datagrid widget (table)
    """


class IDataGridRowWidget(IObjectWidget):
    """Datagrid row widget (table rows)
    """
