import BigWorld
import urllib2
import json
from debug_utils import LOG_CURRENT_EXCEPTION
from gui.Scaleform.daapi.view.lobby.rally.UnitUserCMHandler import UnitUserCMHandler

MOD_LINKAGE  = 'com.roman.custom_info_panel'
SERVER_URL   = 'http://localhost:8082/tanks'
ACTION_ID    = 'showVehicleList'
WINDOW_ALIAS = 'VehicleListWindow'
WINDOW_SWF   = 'vehicleListWindow.swf'

def _log(msg):
    BigWorld.logInfo('CustomInfoPanel', msg, None)

def _err(msg):
    BigWorld.logError('CustomInfoPanel', msg, None)

_pendingAccId = [None]
_pendingName  = [None]
_windowData   = [None]

def _fetchVehicles(account_id):
    url = SERVER_URL + '?account_id=' + str(account_id)
    _log('Fetching: ' + url)
    try:
        response = urllib2.urlopen(url, timeout=5)
        data = json.loads(response.read())
        if isinstance(data, dict):
            data = data.get('tanks', [])
        _log('Got ' + str(len(data)) + ' tanks')
        return data
    except Exception as e:
        _err('fetch error: ' + str(e))
        return []

def _formatTag(tag):
    # Tags are now plain display names, no formatting needed
    return tag, ''

def _buildSettingsData(tanks, player_name):
    col1 = []
    col2 = []
    if tanks:
        mid = (len(tanks) + 1) // 2
        left = tanks[:mid]
        right = tanks[mid:]
        for i, tag in enumerate(left):
            col1.append({'type': 'Label', 'text': str(tag)})
            col2.append({'type': 'Label', 'text': str(right[i]) if i < len(right) else ''})
    else:
        col1.append({'type': 'Label', 'text': 'No vehicles found'})
        col2.append({'type': 'Label', 'text': ''})

    title = (player_name + "'s Vehicles") if player_name else 'Vehicle List'
    return [{
        'linkage':        MOD_LINKAGE,
        'modDisplayName': title,
        'enabled':        True,
        'column1':        col1,
        'column2':        col2,
        'settings':       {},
        'hotkeys':        [],
    }]

def _buildLocalization():
    return {
        'windowTitle':  'Vehicle List',
        'stateTooltip': '',
        'buttonOK':     'OK',
        'buttonCancel': 'Cancel',
        'buttonApply':  'Apply',
        'buttonClose':  'Close',
    }

def _registerWindowView():
    try:
        from gui.Scaleform.framework import g_entitiesFactories, ViewSettings, ScopeTemplates
        from gui.Scaleform.framework.entities.View import View

        class _VehicleListView(View):

            def _populate(self):
                super(_VehicleListView, self)._populate()
                _log('_populate called')
                # Do NOT send data here - requestModsData fires first and handles it

            def _sendData(self):
                if not self.flashObject:
                    _err('flashObject is None')
                    return
                tanks, player_name = _windowData[0] if _windowData[0] else ([], None)
                try:
                    self.flashObject.as_setLocalization(_buildLocalization())
                    self.flashObject.as_setData(_buildSettingsData(tanks, player_name))
                    self.flashObject.as_setHotkeys([])
                    _log('Data sent OK')
                except Exception as e:
                    _err('_sendData error: ' + str(e))

            def requestModsData(self):
                _log('requestModsData called')
                self._sendData()

            def hotKeyAction(self, linkage, varName, action):
                pass

            def buttonAction(self, linkage, varName, value):
                pass

            def closeView(self):
                _log('closeView called')
                self.destroy()

            def _dispose(self):
                _log('_dispose called')
                super(_VehicleListView, self)._dispose()

        g_entitiesFactories.addSettings(
            ViewSettings(
                WINDOW_ALIAS,
                _VehicleListView,
                WINDOW_SWF,
                10,
                None,
                ScopeTemplates.GLOBAL_SCOPE,
            )
        )
        _log('View registered OK')
    except Exception as e:
        _err('_registerWindowView error: ' + str(e))

def _openWindow(tanks, player_name):
    _windowData[0] = (tanks, player_name)
    try:
        from gui.Scaleform.framework.managers.loaders import SFViewLoadParams
        from gui.shared.personality import ServicesLocator
        app = ServicesLocator.appLoader.getDefLobbyApp()
        if app:
            app.loadView(SFViewLoadParams(WINDOW_ALIAS, parent=None), ctx=None)
            _log('loadView called OK')
        else:
            _err('No lobby app')
    except Exception as e:
        _err('open error: ' + str(e))

def _override(module, func_name):
    def decorator(fn):
        original = getattr(module, func_name)
        def wrapper(*args, **kwargs):
            try:
                return fn(original, *args, **kwargs)
            except Exception:
                LOG_CURRENT_EXCEPTION()
                return original(*args, **kwargs)
        setattr(module, func_name, wrapper)
        return wrapper
    return decorator

@_override(UnitUserCMHandler, '_addPrebattleInfo')
def _hookedAddPrebattleInfo(original, self, options, userCMInfo):
    try:
        _pendingAccId[0] = getattr(userCMInfo, 'databaseID', None)
        _pendingName[0]  = getattr(userCMInfo, 'userName', None) or str(_pendingAccId[0])
    except Exception:
        LOG_CURRENT_EXCEPTION()
    options = original(self, options, userCMInfo)
    options.append(self._makeItem(ACTION_ID, 'View Vehicles'))
    return options

@_override(UnitUserCMHandler, 'onOptionSelect')
def _hookedOnOptionSelect(original, self, optionId):
    if optionId == ACTION_ID:
        if _pendingAccId[0]:
            _log('Fetching for: ' + str(_pendingName[0]))
            tanks = _fetchVehicles(_pendingAccId[0])
            _openWindow(tanks, _pendingName[0])
        else:
            _err('No pending account id')
        return
    return original(self, optionId)

_log('init')
_registerWindowView()

def _inspectPopover():
    try:
        from gui.Scaleform.daapi.view.lobby.fortifications.FortVehicleSelectPopover \
            import FortVehicleSelectPopover
        methods = [m for m in dir(FortVehicleSelectPopover) if not m.startswith('__')]
        _log('Popover methods: ' + str(methods))
    except Exception as e:
        _err('inspect error: ' + str(e))

BigWorld.callback(5.0, _inspectPopover)

def _inspectPopover():
    try:
        import gui.Scaleform.daapi.view.lobby.fortifications.FortVehicleSelectPopover as m
        cls = getattr(m, 'FortVehicleSelectPopover', None)
        if cls:
            methods = [x for x in dir(cls) if not x.startswith('__')]
            _log('Popover methods: ' + str(methods))
        else:
            _log('Class not found in module, attrs: ' + str(dir(m)))
    except ImportError as e:
        _err('ImportError: ' + str(e))
        # Try alternate path
        try:
            import gui.Scaleform.daapi.view.lobby.fortifications as fort
            _log('Fort module attrs: ' + str(dir(fort)))
        except Exception as e2:
            _err('Fort module error: ' + str(e2))
    except Exception as e:
        _err('inspect error: ' + str(e))

# Hook into the view loading to catch it at the right moment
try:
    from gui.shared import g_eventBus, EVENT_BUS_SCOPE
    from gui.shared.events import ComponentEvent

    def _onComponentRegistered(event):
        if 'FortVehicle' in str(getattr(event, 'alias', '')):
            _log('FortVehicle component registered: ' + str(event.alias))
            _inspectPopover()

    g_eventBus.addListener(
        ComponentEvent.COMPONENT_REGISTERED,
        _onComponentRegistered,
        EVENT_BUS_SCOPE.GLOBAL
    )
    _log('Component listener registered')
except Exception as e:
    _err('listener error: ' + str(e))

def _inspectPopover():
    try:
        import gui.Scaleform.daapi.view.lobby.fortifications.FortVehicleSelectPopover as m
        cls = getattr(m, 'FortVehicleSelectPopover', None)
        if cls:
            methods = [x for x in dir(cls) if not x.startswith('__')]
            _log('Popover methods: ' + str(methods))
        else:
            _log('Class not found in module, attrs: ' + str(dir(m)))
    except ImportError as e:
        _err('ImportError: ' + str(e))
        # Try alternate path
        try:
            import gui.Scaleform.daapi.view.lobby.fortifications as fort
            _log('Fort module attrs: ' + str(dir(fort)))
        except Exception as e2:
            _err('Fort module error: ' + str(e2))
    except Exception as e:
        _err('inspect error: ' + str(e))

# Hook into the view loading to catch it at the right moment
try:
    from gui.shared import g_eventBus, EVENT_BUS_SCOPE
    from gui.shared.events import ComponentEvent

    def _onComponentRegistered(event):
        if 'FortVehicle' in str(getattr(event, 'alias', '')):
            _log('FortVehicle component registered: ' + str(event.alias))
            _inspectPopover()

    g_eventBus.addListener(
        ComponentEvent.COMPONENT_REGISTERED,
        _onComponentRegistered,
        EVENT_BUS_SCOPE.GLOBAL
    )
    _log('Component listener registered')
except Exception as e:
    _err('listener error: ' + str(e))

def _inspectPopover():
    try:
        import gui.Scaleform.daapi.view.lobby.fortifications.FortVehicleSelectPopover as m
        cls = getattr(m, 'FortVehicleSelectPopover', None)
        if cls:
            methods = [x for x in dir(cls) if not x.startswith('__')]
            _log('Popover methods: ' + str(methods))
        else:
            _log('Class not found in module, attrs: ' + str(dir(m)))
    except ImportError as e:
        _err('ImportError: ' + str(e))
        # Try alternate path
        try:
            import gui.Scaleform.daapi.view.lobby.fortifications as fort
            _log('Fort module attrs: ' + str(dir(fort)))
        except Exception as e2:
            _err('Fort module error: ' + str(e2))
    except Exception as e:
        _err('inspect error: ' + str(e))

# Hook into the view loading to catch it at the right moment
try:
    from gui.shared import g_eventBus, EVENT_BUS_SCOPE
    from gui.shared.events import ComponentEvent

    def _onComponentRegistered(event):
        if 'FortVehicle' in str(getattr(event, 'alias', '')):
            _log('FortVehicle component registered: ' + str(event.alias))
            _inspectPopover()

    g_eventBus.addListener(
        ComponentEvent.COMPONENT_REGISTERED,
        _onComponentRegistered,
        EVENT_BUS_SCOPE.GLOBAL
    )
    _log('Component listener registered')
except Exception as e:
    _err('listener error: ' + str(e))
