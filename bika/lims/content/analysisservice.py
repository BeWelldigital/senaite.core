# -*- coding: utf-8 -*-

# This file is part of Bika LIMS
#
# Copyright 2011-2016 by it's authors.
# Some rights reserved. See LICENSE.txt, AUTHORS.txt.


import sys

import transaction
from AccessControl import ClassSecurityInfo
from Products.ATExtensions.ateapi import RecordsField
from Products.Archetypes.Registry import registerField
from Products.Archetypes.public import DisplayList, BooleanField, \
    BooleanWidget, Schema, registerType, SelectionWidget, MultiSelectionWidget
from Products.CMFCore.WorkflowCore import WorkflowException
from Products.CMFCore.utils import getToolByName
from bika.lims import PMF, bikaMessageFactory as _
from bika.lims.browser.fields import UIDReferenceField
from bika.lims.browser.widgets.partitionsetupwidget import PartitionSetupWidget
from bika.lims.browser.widgets.referencewidget import ReferenceWidget
from bika.lims.config import PROJECTNAME
from bika.lims.content.baseanalysis import BaseAnalysis
from bika.lims.content.baseanalysis import schema as BaseAnalysisSchema
from bika.lims.interfaces import IAnalysisService, IHaveIdentifiers
from bika.lims.utils import to_utf8 as _c
from magnitude import mg
from plone.api.portal import get_tool
from plone.indexer import indexer
from zope.interface import implements


def getContainers(instance,
                  minvol=None,
                  allow_blank=True,
                  show_container_types=True,
                  show_containers=True):
    """ Containers vocabulary

    This is a separate class so that it can be called from ajax to filter
    the container list, as well as being used as the AT field vocabulary.

    Returns a tuple of tuples: ((object_uid, object_title), ())

    If the partition is flagged 'Separate', only containers are displayed.
    If the Separate flag is false, displays container types.

    XXX bsc = self.portal.bika_setup_catalog
    XXX obj = bsc(getKeyword='Moist')[0].getObject()
    XXX u'Container Type: Canvas bag' in obj.getContainers().values()
    XXX True

    """

    bsc = getToolByName(instance, 'bika_setup_catalog')

    items = allow_blank and [['', _('Any')]] or []

    containers = []
    for container in bsc(portal_type='Container', sort_on='sortable_title'):
        container = container.getObject()

        # verify container capacity is large enough for required sample volume.
        if minvol is not None:
            capacity = container.getCapacity()
            try:
                capacity = capacity.split(' ', 1)
                capacity = mg(float(capacity[0]), capacity[1])
                if capacity < minvol:
                    continue
            except (ValueError, TypeError):
                # if there's a unit conversion error, allow the container
                # to be displayed.
                pass

        containers.append(container)

    if show_containers:
        # containers with no containertype first
        for container in containers:
            if not container.getContainerType():
                items.append((container.UID(), container.Title()))

    ts = getToolByName(instance, 'translation_service').translate
    cat_str = _c(ts(_('Container Type')))
    containertypes = [c.getContainerType() for c in containers]
    containertypes = dict([(ct.UID(), ct.Title())
                           for ct in containertypes if ct])
    for ctype_uid, ctype_title in containertypes.items():
        ctype_title = _c(ctype_title)
        if show_container_types:
            items.append((ctype_uid, "%s: %s" % (cat_str, ctype_title)))
        if show_containers:
            for container in containers:
                ctype = container.getContainerType()
                if ctype and ctype.UID() == ctype_uid:
                    items.append((container.UID(), container.Title()))

    items = tuple(items)
    return items


class PartitionSetupField(RecordsField):
    _properties = RecordsField._properties.copy()
    _properties.update({
        'subfields': (
            'sampletype',
            'separate',
            'preservation',
            'container',
            'vol',
            # 'retentionperiod',
        ),
        'subfield_labels': {
            'sampletype': _('Sample Type'),
            'separate': _('Separate Container'),
            'preservation': _('Preservation'),
            'container': _('Container'),
            'vol': _('Required Volume'),
            # 'retentionperiod': _('Retention Period'),
        },
        'subfield_types': {
            'separate': 'boolean',
            'vol': 'string',
            'container': 'selection',
            'preservation': 'selection',
        },
        'subfield_vocabularies': {
            'sampletype': 'SampleTypes',
            'preservation': 'Preservations',
            'container': 'Containers',
        },
        'subfield_sizes': {
            'sampletype': 1,
            'preservation': 6,
            'vol': 8,
            'container': 6,
            # 'retentionperiod':10,
        }
    })
    security = ClassSecurityInfo()

    security.declarePublic('SampleTypes')

    def SampleTypes(self, instance=None):
        instance = instance or self
        bsc = getToolByName(instance, 'bika_setup_catalog')
        items = []
        for st in bsc(portal_type='SampleType',
                      inactive_state='active',
                      sort_on='sortable_title'):
            st = st.getObject()
            title = st.Title()
            items.append((st.UID(), title))
        items = [['', '']] + list(items)
        return DisplayList(items)

    security.declarePublic('Preservations')

    def Preservations(self, instance=None):
        instance = instance or self
        bsc = getToolByName(instance, 'bika_setup_catalog')
        items = [(c.UID, c.title) for c in
                 bsc(portal_type='Preservation',
                     inactive_state='active',
                     sort_on='sortable_title')]
        items = [['', _('Any')]] + list(items)
        return DisplayList(items)

    security.declarePublic('Containers')

    def Containers(self, instance=None):
        instance = instance or self
        items = getContainers(instance, allow_blank=True)
        return DisplayList(items)


registerField(PartitionSetupField, title="", description="")


@indexer(IAnalysisService)
def sortable_title_with_sort_key(instance):
    sort_key = instance.getSortKey()
    if sort_key:
        return "{:010.3f}{}".format(sort_key, instance.Title())
    return instance.Title()

# If this flag is true, then analyses created from this service will be linked
# to their own Sample Partition, and no other analyses will be linked to that
# partition.
Separate = BooleanField(
    'Separate',
    schemata='Container and Preservation',
    default=False,
    required=0,
    widget=BooleanWidget(
        label=_("Separate Container"),
        description=_("Check this box to ensure a separate sample container is "
                      "used for this analysis service"),
    )
)

# The preservation for this service; If multiple services share the same
# preservation, then it's possible that they can be performed on the same
# sample partition.
Preservation = UIDReferenceField(
    'Preservation',
    schemata='Container and Preservation',
    allowed_types=('Preservation',),
    vocabulary='getPreservations',
    required=0,
    multiValued=0,
    widget=ReferenceWidget(
        checkbox_bound=0,
        label=_("Default Preservation"),
        description=_(
            "Select a default preservation for this analysis service. If the "
            "preservation depends on the sample type combination, specify a "
            "preservation per sample type in the table below"),
        catalog_name='bika_setup_catalog',
        base_query={'inactive_state': 'active'},
    )
)

# The container or containertype for this service's analyses can be specified.
# If multiple services share the same container or containertype, then it's
# possible that their analyses can be performed on the same partitions
Container = UIDReferenceField(
    'Container',
    schemata='Container and Preservation',
    allowed_types=('Container', 'ContainerType'),
    vocabulary='getContainers',
    required=0,
    multiValued=0,
    widget=ReferenceWidget(
        checkbox_bound=0,
        label=_("Default Container"),
        description=_(
            "Select the default container to be used for this analysis "
            "service. If the container to be used depends on the sample type "
            "and preservation combination, specify the container in the "
            "sample type table below"),
        catalog_name='bika_setup_catalog',
        base_query={'inactive_state': 'active'},
    )
)

# This is a list of dictionaries which contains the PartitionSetupWidget
# settings.  This is used to decide how many distinct physical partitions
# will be created, which containers/preservations they will use, and which
# analyases can be performed on each partition.
PartitionSetup = PartitionSetupField(
    'PartitionSetup',
    schemata='Container and Preservation',
    widget=PartitionSetupWidget(
        label=PMF("Preservation per sample type"),
        description=_(
            "Please specify preservations that differ from the analysis "
            "service's default preservation per sample type here."),
    )
)

# Allow/Disallow to set the calculation manually
# Behavior controlled by javascript depending on Instruments field:
# - If no instruments available, hide and uncheck
# - If at least one instrument selected then checked, but not readonly
# See browser/js/bika.lims.analysisservice.edit.js
UseDefaultCalculation = BooleanField(
    'UseDefaultCalculation',
    schemata="Method",
    default=True,
    widget=BooleanWidget(
        label=_("Use default calculation"),
        description=_(
            "Select if the calculation to be used is the calculation set by "
            "default in the default method. If unselected, the calculation "
            "can be selected manually"),
    )
)

# Manual methods associated to the AS
# List of methods capable to perform the Analysis Service. The
# Methods selected here are displayed in the Analysis Request
# Add view, closer to this Analysis Service if selected.
# Use getAvailableMethods() to retrieve the list with methods both
# from selected instruments and manually entered.
# Behavior controlled by js depending on ManualEntry/Instrument:
# - If InsrtumentEntry not checked, show
# See browser/js/bika.lims.analysisservice.edit.js
Methods = UIDReferenceField(
    'Methods',
    schemata="Method",
    required=0,
    multiValued=1,
    vocabulary='_getAvailableMethodsDisplayList',
    allowed_types=('Method',),
    widget=MultiSelectionWidget(
        label=_("Methods"),
        description=_(
            "The tests of this type of analysis can be performed by using "
            "more than one method with the 'Manual entry of results' option "
            "enabled. A selection list with the methods selected here is "
            "populated in the manage results view for each test of this type "
            "of analysis. Note that only methods with 'Allow manual entry' "
            "option enabled are displayed here; if you want the user to be "
            "able to assign a method that requires instrument entry, enable "
            "the 'Instrument assignment is allowed' option."),
    )
)

# Instruments associated to the AS
# List of instruments capable to perform the Analysis Service. The
# Instruments selected here are displayed in the Analysis Request
# Add view, closer to this Analysis Service if selected.
# - If InstrumentEntry not checked, hide and unset
# - If InstrumentEntry checked, set the first selected and show
Instruments = UIDReferenceField(
    'Instruments',
    schemata="Method",
    required=0,
    multiValued=1,
    vocabulary='_getAvailableInstrumentsDisplayList',
    allowed_types=('Instrument',),
    widget=MultiSelectionWidget(
        label=_("Instruments"),
        description=_(
            "More than one instrument can be used in a test of this type of "
            "analysis. A selection list with the instruments selected here is "
            "populated in the results manage view for each test of this type "
            "of analysis. The available instruments in the selection list "
            "will change in accordance with the method selected by the user "
            "for that test in the manage results view. Although a method can "
            "have more than one instrument assigned, the selection list is "
            "only populated with the instruments that are both set here and "
            "allowed for the selected method."),
    )
)

schema = BaseAnalysisSchema.copy() + Schema((
    Separate,
    Preservation,
    Container,
    PartitionSetup,
    UseDefaultCalculation,
    Methods,
    Instruments,
))


class AnalysisService(BaseAnalysis):
    security = ClassSecurityInfo()
    schema = schema
    displayContentsTab = False
    implements(IAnalysisService, IHaveIdentifiers)

    _at_rename_after_creation = True

    def _renameAfterCreation(self, check_auto_id=False):
        from bika.lims.idserver import renameAfterCreation

        return renameAfterCreation(self)

    security.declarePublic('getContainers')

    def getContainers(self, instance=None):
        # On first render, the containers must be filtered
        instance = instance or self
        separate = self.getSeparate()
        containers = getContainers(instance,
                                   allow_blank=True,
                                   show_container_types=not separate,
                                   show_containers=separate)
        return DisplayList(containers)

    def getPreservations(self):
        bsc = getToolByName(self, 'bika_setup_catalog')
        items = [(o.UID, o.Title) for o in
                 bsc(portal_type='Preservation', inactive_state='active')]
        items.sort(lambda x, y: cmp(x[1], y[1]))
        return DisplayList(list(items))

    @security.public
    def getAvailableMethods(self):
        """ Returns the methods available for this analysis.
            If the service has the getInstrumentEntryOfResults(), returns
            the methods available from the instruments capable to perform
            the service, as well as the methods set manually for the
            analysis on its edit view. If getInstrumentEntryOfResults()
            is unset, only the methods assigned manually to that service
            are returned.
        """
        methods = self.getMethods()
        muids = [m.UID() for m in methods]
        if self.getInstrumentEntryOfResults():
            # Add the methods from the instruments capable to perform
            # this analysis service
            for ins in self.getInstruments():
                for method in ins.getMethods():
                    if method and method.UID() not in muids:
                        methods.append(method)
                        muids.append(method.UID())

        return methods

    @security.public
    def getAvailableMethodsUIDs(self):
        """ Returns the UIDs of the available method.
        """
        return [m.UID() for m in self.getAvailableMethods()]

    @security.public
    def getAvailableInstruments(self):
        """ Returns the instruments available for this service.
            If the service has the getInstrumentEntryOfResults(), returns
            the instruments capable to perform this service. Otherwhise,
            returns an empty list.
        """
        instruments = self.getInstruments() \
            if self.getInstrumentEntryOfResults() is True \
            else None
        return instruments if instruments else []

    @security.private
    def _getAvailableMethodsDisplayList(self):
        """ Returns a DisplayList with the available Methods
            registered in Bika-Setup. Only active Methods and those
            with Manual Entry field active are fetched.
            Used to fill the Methods MultiSelectionWidget when 'Allow
            Instrument Entry of Results is not selected'.
        """
        bsc = get_tool('bika_setup_catalog')
        items = [(i.UID, i.Title)
                 for i in bsc(portal_type='Method',
                              inactive_state='active')
                 if i.getObject().isManualEntryOfResults()]
        items.sort(lambda x, y: cmp(x[1], y[1]))
        items.insert(0, ('', _("None")))
        return DisplayList(list(items))

    @security.private
    def _getAvailableCalculationsDisplayList(self):
        """ Returns a DisplayList with the available Calculations
            registered in Bika-Setup. Only active Calculations are
            fetched. Used to fill the Calculation field
        """
        bsc = get_tool('bika_setup_catalog')
        items = [(i.UID, i.Title)
                 for i in bsc(portal_type='Calculation',
                              inactive_state='active')]
        items.sort(lambda x, y: cmp(x[1], y[1]))
        items.insert(0, ('', _("None")))
        return DisplayList(list(items))

    @security.private
    def _getAvailableInstrumentsDisplayList(self):
        """ Returns a DisplayList with the available Instruments
            registered in Bika-Setup. Only active Instruments are
            fetched. Used to fill the Instruments MultiSelectionWidget
        """
        bsc = get_tool('bika_setup_catalog')
        items = [(i.UID, i.Title)
                 for i in bsc(portal_type='Instrument',
                              inactive_state='active')]
        items.sort(lambda x, y: cmp(x[1], y[1]))
        return DisplayList(list(items))

    def workflow_script_activate(self):
        workflow = getToolByName(self, 'portal_workflow')
        pu = getToolByName(self, 'plone_utils')
        # A service cannot be activated if it's calculation is inactive
        calc = self.getCalculation()
        inactive_state = workflow.getInfoFor(calc, "inactive_state")
        if calc and inactive_state == "inactive":
            message = _(
                "This Analysis Service cannot be activated because it's "
                "calculation is inactive.")
            pu.addPortalMessage(message, 'error')
            transaction.get().abort()
            raise WorkflowException

    def workflow_scipt_deactivate(self):
        bsc = getToolByName(self, 'bika_setup_catalog')
        pu = getToolByName(self, 'plone_utils')
        # A service cannot be deactivated if "active" calculations list it
        # as a dependency.
        active_calcs = bsc(portal_type='Calculation', inactive_state="active")
        calculations = (c.getObject() for c in active_calcs)
        for calc in calculations:
            deps = [dep.UID() for dep in calc.getDependentServices()]
            if self.UID() in deps:
                message = _(
                    "This Analysis Service cannot be deactivated because one "
                    "or more active calculations list it as a dependency")
                pu.addPortalMessage(message, 'error')
                transaction.get().abort()
                raise WorkflowException


registerType(AnalysisService, PROJECTNAME)
