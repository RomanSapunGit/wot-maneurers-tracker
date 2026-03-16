import BigWorld
from debug_utils import LOG_CURRENT_EXCEPTION
from gui import SystemMessages
from gui.Scaleform.daapi.view.lobby.rally.UnitUserCMHandler import UnitUserCMHandler
from items import vehicles as veh_items

IS_MOD_ENABLED = True
ACTION_ID = 'showTankList'

# -------------------------------------------------------
# Configure which vehicles to display in the list here.
# -------------------------------------------------------
TANK_LIST = [
    'uk:GB98_T95_FV4201_Chieftain',
    'france:F72_AMX_30',
    'ussr:R04_T-34',
    'germany:G04_PzVI_Tiger_I',
]
# -------------------------------------------------------

_pending_account_id = None
_pending_player_name = None


def push_system_msg(text):
    SystemMessages.pushMessage(text, SystemMessages.SM_TYPE.Information)


def override_func(target_module, func_name):
    def decorator(wrapped_function):
        original_function = getattr(target_module, func_name)
        def wrapper(*args, **kwargs):
            try:
                return wrapped_function(original_function, *args, **kwargs)
            except Exception:
                LOG_CURRENT_EXCEPTION()
                return original_function(*args, **kwargs)
        setattr(target_module, func_name, wrapper)
        return wrapper
    return decorator


def _show_vehicle_list(player_name):
    """
    Shows a popup with the configured vehicle list.
    Added a delay to wait for game state transitions.
    """
    print '[mod_chieftain] Showing vehicle list for: {}'.format(player_name)
    # 1.0s delay to wait for game state transitions
    BigWorld.callback(1.0, lambda: _do_load_vehicle_popup())


def _do_load_vehicle_popup():
    from gui.shared import g_eventBus, EVENT_BUS_SCOPE
    from gui.shared.events import LoadViewEvent
    from gui.Scaleform.framework.managers.loaders import SFViewLoadParams
    from helpers import dependency
    
    basket = None
    try:
        from skeletons.gui.game_control import IVehicleComparisonBasket
        basket = dependency.instance(IVehicleComparisonBasket)
    except ImportError:
        try:
            from skeletons.gui.shared import IVehicleComparisonBasket
            basket = dependency.instance(IVehicleComparisonBasket)
        except ImportError:
            print '[mod_chieftain] Critical: Could not import IVehicleComparisonBasket'

    if basket is not None:
        print '[mod_chieftain] Populating comparison basket'
        try:
            # Try to clear existing items to show only our list
            for clear_method in ('clear', 'removeAll', 'removeVehicles'):
                if hasattr(basket, clear_method):
                    try:
                        getattr(basket, clear_method)()
                        print '[mod_chieftain] Basket cleared using {}'.format(clear_method)
                        break
                    except Exception:
                        pass
            else:
                # Fallback: manually remove if getVehiclesCDs exists
                if hasattr(basket, 'getVehiclesCDs') and hasattr(basket, 'removeVehicle'):
                    for cd in list(basket.getVehiclesCDs()):
                        basket.removeVehicle(cd)

            # Add our tanks
            count = 0
            for tank_name in TANK_LIST:
                try:
                    cd = veh_items.makeVehicleTypeCompDescrByName(tank_name)
                    basket.addVehicle(cd)
                    count += 1
                except Exception as e:
                    print '[mod_chieftain] Failed to add {}: {}'.format(tank_name, e)
            print '[mod_chieftain] Added {} vehicles to basket'.format(count)
        except Exception as e:
            print '[mod_chieftain] Basket population error: {}'.format(e)

    # Trigger the popup
    # We are returning to the 'vehicleCompareConfigurator' alias which shows the 
    # detailed configuration/stats window for a single vehicle (usually the first one in the basket).
    try:
        loadParams = SFViewLoadParams('vehicleCompareConfigurator')
        # We pass index=0 and matching ctx to satisfy the game's state machine for this specific window.
        event = LoadViewEvent(loadParams, ctx={'isMain': True, 'index': 0}, index=0)
        g_eventBus.handleEvent(event, scope=EVENT_BUS_SCOPE.LOBBY)
        print '[mod_chieftain] Fired LoadViewEvent for vehicleCompareConfigurator'
        return
    except Exception as e:
        print '[mod_chieftain] Failed to load configurator: {}'.format(e)

    push_system_msg('Configured vehicles added to comparison table.')


def _fetch_and_show(account_id, player_name):
    print '[mod_chieftain] Displaying vehicle list for player: {}'.format(player_name)
    _show_vehicle_list(player_name)


@override_func(UnitUserCMHandler, '_addPrebattleInfo')
def hooked_addPrebattleInfo(original_func, self, options, userCMInfo):
    global _pending_account_id, _pending_player_name
    try:
        _pending_account_id = getattr(userCMInfo, 'databaseID', None)
        _pending_player_name = getattr(userCMInfo, 'userName', None) or str(_pending_account_id)
    except Exception:
        LOG_CURRENT_EXCEPTION()
    options = original_func(self, options, userCMInfo)
    if IS_MOD_ENABLED:
        options.append(self._makeItem(ACTION_ID, 'View Vehicles'))
    return options


@override_func(UnitUserCMHandler, 'onOptionSelect')
def hooked_onOptionSelect(original_func, self, optionId):
    if optionId == ACTION_ID:
        if _pending_account_id:
            _fetch_and_show(_pending_account_id, _pending_player_name)
        else:
            push_system_msg('Could not determine player.')
        return
    return original_func(self, optionId)


def init():
    print '[mod_chieftain] Loaded. {} vehicles configured.'.format(len(TANK_LIST))
    push_system_msg('Tank Viewer Mod Loaded.')

init()