import BigWorld
import urllib2
import json
from debug_utils import LOG_CURRENT_EXCEPTION
from gui.Scaleform.daapi.view.lobby.rally.UnitUserCMHandler import UnitUserCMHandler

MOD_LINKAGE  = 'com.roman.custom_info_panel'
SERVER_URL   = 'http://localhost:8082/tanks'
ACTION_ID    = 'showVehicleList'

def _log(msg):
    BigWorld.logInfo('CustomInfoPanel', msg, None)

def _err(msg):
    BigWorld.logError('CustomInfoPanel', msg, None)

_pendingAccId     = [None]
_pendingName      = [None]
_fetchedTanks     = [None]
_interceptNext    = [False]
_battleRoomRef    = [None]
_injectedVehicles = [None]


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


def _buildVehicleDict(tank_data):
    try:
        from helpers import dependency
        from skeletons.gui.shared import IItemsCache
        from items import vehicles as veh_items
        itemsCache = dependency.instance(IItemsCache)
        if not tank_data:
            return {}
        result = {}
        for entry in tank_data:
            try:
                tag = entry.get('tag')
                is_destroyed = entry.get('destroyed', False)
                cd = veh_items.makeVehicleTypeCompDescrByName(str(tag))
                synthetic_veh = _createSyntheticVehicle(cd, itemsCache, is_destroyed)
                if synthetic_veh is not None:
                    result[cd] = synthetic_veh
            except Exception as e:
                _log('Could not resolve: ' + str(entry) + ': ' + str(e))
        _log('Built synthetic vehicle dict: ' + str(len(result)))
        return result
    except Exception as e:
        _err('_buildVehicleDict error: ' + str(e))
        return {}


def _createSyntheticVehicle(compact_descr, itemsCache, is_destroyed=False):
    try:
        from gui.shared.utils.requesters import REQ_CRITERIA
        player_vehicles = itemsCache.items.getVehicles(REQ_CRITERIA.INVENTORY)
        template = None
        for veh in player_vehicles.itervalues():
            if veh.intCD == compact_descr:
                template = veh
                break
        if template is not None:
            return _stripInventoryState(template, is_destroyed)
        return _createFromDescriptor(compact_descr, is_destroyed)
    except Exception as e:
        _err('_createSyntheticVehicle error: ' + str(e))
        return None


def _stripInventoryState(vehicle, is_destroyed=False):
    try:
        class CleanVehicleProxy(object):
            def __init__(self, base_vehicle, destroyed):
                self._base = base_vehicle
                self.is_destroyed = destroyed

            @property
            def intCD(self):
                return self._base.intCD

            @property
            def name(self):
                return self._base.name

            @property
            def userName(self):
                return self._base.userName

            @property
            def level(self):
                return self._base.level

            @property
            def type(self):
                return self._base.type

            @property
            def descriptor(self):
                return self._base.descriptor

            @property
            def hasCrew(self):
                return True

            @property
            def isCrewFull(self):
                return True

            @property
            def crewCompactDescrs(self):
                return []

            @property
            def equipment(self):
                return []

            @property
            def shells(self):
                return []

            @property
            def isReadyToFight(self):
                return not self.is_destroyed

            @property
            def isBroken(self):
                return self.is_destroyed

            @property
            def repairCost(self):
                return 0

            @property
            def isLocked(self):
                return self.is_destroyed

            @property
            def clanLock(self):
                return 0

            @property
            def isRented(self):
                return False

            @property
            def rentalIsOver(self):
                return False

            def __getattr__(self, name):
                return getattr(self._base, name)

        return CleanVehicleProxy(vehicle, is_destroyed)
    except Exception as e:
        _err('_stripInventoryState error: ' + str(e))
        return vehicle


def _createFromDescriptor(compact_descr, is_destroyed=False):
    try:
        from items.vehicles import VehicleDescr
        type_descr = VehicleDescr(compactDescr=compact_descr)

        class GhostVehicle(object):
            def __init__(self, descr, destroyed):
                self._descr = descr
                self.intCD = compact_descr
                self.is_destroyed = destroyed

            @property
            def descriptor(self):
                return self._descr

            @property
            def name(self):
                return self._descr.name

            @property
            def userName(self):
                return self._descr.type.userString

            @property
            def level(self):
                return self._descr.level

            @property
            def type(self):
                return self._descr.type.tags

            @property
            def hasCrew(self):
                return True

            @property
            def isCrewFull(self):
                return True

            @property
            def crewCompactDescrs(self):
                return []

            @property
            def isReadyToFight(self):
                return not self.is_destroyed

            @property
            def isBroken(self):
                return self.is_destroyed

            @property
            def isLocked(self):
                return self.is_destroyed

            @property
            def isRented(self):
                return False

        return GhostVehicle(type_descr, is_destroyed)
    except Exception as e:
        _err('_createFromDescriptor error: ' + str(e))
        return None


def _cleanupVO(vo, vehicle=None):
    """Only touch keys that exist in VehicleSelectorItemVO schema."""
    is_destroyed = getattr(vehicle, 'is_destroyed', False) if vehicle else False
    vo['isReadyToFight'] = not is_destroyed
    vo['enabled'] = not is_destroyed
    vo['state'] = 'destroyed' if is_destroyed else ''
    return vo


_inLogic = [False]

def _applyInjection(self, vehicle_dict):
    if _inLogic[0]:
        return
    _injectedVehicles[0] = vehicle_dict
    self._vehicles = vehicle_dict
    _log('Applying injection: ' + str(len(vehicle_dict)) + ' vehicles')
    try:
        # Final filter state detection based on diagnostic logs
        show_not_ready = True
        filters = getattr(self, '_VehicleSelectorBase__filters', {})
        if isinstance(filters, dict) and 'compatibleOnly' in filters:
            show_not_ready = not filters['compatibleOnly']
            _log('Filter state: show_not_ready=' + str(show_not_ready) + ' (via compatibleOnly)')
        else:
            # Fallback for other selector types
            _log('Filter state: compatibleOnly not found in ' + str(filters))
        
        vo_list = []
        for cd, vehicle in vehicle_dict.items():
            try:
                vo = self._makeVehicleVOAction(vehicle)
                if vo is not None:
                    vo = _cleanupVO(vo, vehicle)
                    
                    # Manual filter check
                    if not show_not_ready and not vo.get('isReadyToFight', True):
                        continue
                        
                    vo_list.append(vo)
            except Exception as e:
                _log('VO build error for ' + str(cd) + ': ' + str(e))

        _log('Built ' + str(len(vo_list)) + ' VOs (total injected: ' + str(len(vehicle_dict)) + ')')
        self.as_setListDataS(vo_list, [])
    except Exception as e:
        _err('_applyInjection error: ' + str(e))
        _injectedVehicles[0] = None


def _hookBattleRoom():
    try:
        import gui.Scaleform.daapi.view.lobby.fortifications.stronghold_battle_room as m
        cls = m.StrongholdBattleRoom

        original_populate = cls._populate

        def patched_populate(self, *args, **kwargs):
            _log('StrongholdBattleRoom captured')
            _battleRoomRef[0] = self
            return original_populate(self, *args, **kwargs)

        cls._populate = patched_populate

        original_dispose = cls._dispose

        def patched_dispose(self, *args, **kwargs):
            if _battleRoomRef[0] is self:
                _battleRoomRef[0] = None
            return original_dispose(self, *args, **kwargs)

        cls._dispose = patched_dispose
        _log('StrongholdBattleRoom hooks installed')
    except Exception as e:
        _err('_hookBattleRoom error: ' + str(e))


def _hookVehicleSelector():
    try:
        import gui.Scaleform.daapi.view.lobby.cyberSport.VehicleSelectorPopup as m
        cls = m.VehicleSelectorPopup

        original_updateData       = cls._updateData
        original_updateDataPublic = cls.updateData
        original_onFiltersUpdate  = cls.onFiltersUpdate
        original_setListData      = cls.as_setListDataS
        original_dispose          = cls._dispose

        # ----------------------------------------------------------------
        # as_setListDataS — diagnostic only
        # ----------------------------------------------------------------
        def patched_setListData(self, data, selectedData=None):
            _log('as_setListDataS called, len=' + str(len(data) if data else 0))
            return original_setListData(self, data, selectedData)

        cls.as_setListDataS = patched_setListData

        # ----------------------------------------------------------------
        # _updateData (private, called with criteria arg)
        # ----------------------------------------------------------------
        def patched_updateData(self, criteria, *args, **kwargs):
            if _interceptNext[0] and _fetchedTanks[0] is not None:
                _log('_updateData intercepted')
                _interceptNext[0] = False
                vehicle_dict = _buildVehicleDict(_fetchedTanks[0])
                if vehicle_dict:
                    _applyInjection(self, vehicle_dict)
                    return
            return original_updateData(self, criteria, *args, **kwargs)

        cls._updateData = patched_updateData

        # ----------------------------------------------------------------
        # updateData (public)
        # ----------------------------------------------------------------
        def patched_updateDataPublic(self, *args, **kwargs):
            _log('updateData called, injected=' + str(_injectedVehicles[0] is not None))
            if _injectedVehicles[0] is not None:
                _applyInjection(self, _injectedVehicles[0])
                return
            if _interceptNext[0] and _fetchedTanks[0] is not None:
                _log('updateData no-args intercept')
                _interceptNext[0] = False
                vehicle_dict = _buildVehicleDict(_fetchedTanks[0])
                if vehicle_dict:
                    _applyInjection(self, vehicle_dict)
                return
            if not args and not kwargs:
                _log('updateData no args, nothing to inject - skipping')
                return
            return original_updateDataPublic(self, *args, **kwargs)

        cls.updateData = patched_updateDataPublic

        # ----------------------------------------------------------------
        # showNotReadyVehicles — capture the filter state
        # ----------------------------------------------------------------
        original_showNotReadyVehicles = cls.showNotReadyVehicles
        def patched_showNotReadyVehicles(self, show, *args, **kwargs):
            _log('showNotReadyVehicles callback: ' + str(show))
            self._customShowNotReady = show
            return original_showNotReadyVehicles(self, show, *args, **kwargs)

        cls.showNotReadyVehicles = patched_showNotReadyVehicles

        # ----------------------------------------------------------------
        # onFiltersUpdate — intercept to trigger re-injection
        # ----------------------------------------------------------------
        def patched_onFiltersUpdate(self, *args, **kwargs):
            _log('onFiltersUpdate intercepted - calling original')
            _inLogic[0] = True
            try:
                original_onFiltersUpdate(self, *args, **kwargs)
            finally:
                _inLogic[0] = False
                
            if _injectedVehicles[0] is not None:
                _applyInjection(self, _injectedVehicles[0])
            return

        cls.onFiltersUpdate = patched_onFiltersUpdate

        # ----------------------------------------------------------------
        # _dispose — clear state when popup closes
        # ----------------------------------------------------------------
        def patched_dispose(self, *args, **kwargs):
            _injectedVehicles[0] = None
            _fetchedTanks[0] = None
            return original_dispose(self, *args, **kwargs)

        cls._dispose = patched_dispose
        _log('VehicleSelectorPopup hooked')
    except Exception as e:
        _err('_hookVehicleSelector error: ' + str(e))


def _openVehicleSelector(tanks, player_name):
    _log('Opening for: ' + str(player_name))
    _fetchedTanks[0] = tanks
    _interceptNext[0] = True
    _injectedVehicles[0] = None
    room = _battleRoomRef[0]
    if room is not None:
        try:
            room._chooseVehicleRequest((1, 2, 3, 4, 5, 6, 7, 8, 9, 10))
            _log('_chooseVehicleRequest OK')
            return
        except Exception as e:
            _err('_chooseVehicleRequest error: ' + str(e))
    _err('No StrongholdBattleRoom instance')
    _interceptNext[0] = False


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
            _openVehicleSelector(tanks, _pendingName[0])
        else:
            _err('No pending account id')
        return
    return original(self, optionId)


_log('init')
_hookBattleRoom()
_hookVehicleSelector()
