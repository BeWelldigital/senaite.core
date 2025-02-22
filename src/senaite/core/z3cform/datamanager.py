# -*- coding: utf-8 -*-

from senaite.core.schema.interfaces import IBaseField
from z3c.form.datamanager import AttributeField
from z3c.form.datamanager import DictionaryField
from zope.component import adapts
from zope.interface import Interface


class AttributeDataManager(AttributeField):
    """Senaite Data Manager for Attribute Fields

    Original implementation: `z3c.form.datamanager`

    NOTE: The original implementation does not use the setter/getter of the
          field, see z3c/form/datamanager.txt for explanation.

    However, we want to have that control at field level and also be able to
    execute some custom logic when getting/setting the values, e.g. fire
    modification events, check permissions, audit-logging etc.
    """
    adapts(Interface, IBaseField)

    def __init__(self, context, field):
        super(AttributeDataManager, self).__init__(context, field)

    def get(self):
        """Delegate to the field getter
        """
        return self.field.get(self.adapted_context)

    def set(self, value):
        """Delegate to the field setter
        """
        self.field.set(self.adapted_context, value)


class DictionaryDataManager(DictionaryField):
    """Senaite Data Manager for Dictionary Fields

    Original implementation: `z3c.form.datamanager`

    Currently only implemented as a boiler plate for eventual later use.
    """
    adapts(dict, IBaseField)

    def __init__(self, data, field):
        super(DictionaryDataManager, self).__init__(data, field)
