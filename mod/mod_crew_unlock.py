import BigWorld
from debug_utils import LOG_CURRENT_EXCEPTION

def _log(msg):
    BigWorld.logInfo('CrewUnlock', msg, None)

def _err(msg):
    BigWorld.logError('CrewUnlock', msg, None)


def _hook():
    try:
        import gui.Scaleform.daapi.view.lobby.fortifications.fort_vehicle_select_popover as m

        # ----------------------------------------------------------------
        # 1. Patch _IGNORED_VEHICLE_STATES to suppress crew-related blocks
        # ----------------------------------------------------------------
        if hasattr(m, '_IGNORED_VEHICLE_STATES') and hasattr(m, 'Vehicle'):
            try:
                VS = m.Vehicle.VEHICLE_STATE
                states_to_ignore = set(m._IGNORED_VEHICLE_STATES)
                for state_name in ('CREW_NOT_FULL', 'CREW_NOT_FULL_LOCK',
                                   'NOT_FULLY_CREWED', 'CREWNOTFULL'):
                    if hasattr(VS, state_name):
                        states_to_ignore.add(getattr(VS, state_name))
                        _log('Added to ignored states: ' + state_name)
                m._IGNORED_VEHICLE_STATES = tuple(states_to_ignore)
            except Exception as e:
                _err('Could not patch _IGNORED_VEHICLE_STATES: ' + str(e))

        # ----------------------------------------------------------------
        # 2. Inspect criteria conditions to find the crew check
        # ----------------------------------------------------------------
        if hasattr(m, 'getVehicleCriteria') and hasattr(m, 'REQ_CRITERIA'):
            original_getVehicleCriteria = m.getVehicleCriteria

            def patched_getVehicleCriteria(*args, **kwargs):
                criteria = original_getVehicleCriteria(*args, **kwargs)
                for i, cond in enumerate(criteria._conditions):
                    _log('condition[' + str(i) + ']: ' + str(type(cond).__name__))
                    if hasattr(cond, 'predicate'):
                        _log('  predicate: ' + str(cond.predicate))
                    if hasattr(cond, 'predicates'):
                        for j, p in enumerate(cond.predicates):
                            _log('  predicate[' + str(j) + ']: ' + str(p))
                return criteria

            m.getVehicleCriteria = patched_getVehicleCriteria
            _log('getVehicleCriteria patched')

        # ----------------------------------------------------------------
        # 3. Patch _makeVehicleVOAction to force-enable crewless rows
        # ----------------------------------------------------------------
        cls = m.FortVehicleSelectPopover
        original_makeVO = cls._makeVehicleVOAction

        def patched_makeVO(self, vehicle, *args, **kwargs):
            vo = original_makeVO(self, vehicle, *args, **kwargs)
            if vo is not None and isinstance(vo, dict):
                if not vo.get('enabled', True):
                    if not getattr(vehicle, 'isCrewFull', True):
                        vo['enabled'] = True
                        _log('Unlocked: ' + str(getattr(vehicle, 'userName', '?')))
            return vo

        cls._makeVehicleVOAction = patched_makeVO
        _log('All hooks installed OK')

    except Exception as e:
        _err('hook error: ' + str(e))
        LOG_CURRENT_EXCEPTION()


def _hookWulfWindows():
    try:
        from frameworks.wulf.windows_system import window as wnd_module
        original_init = wnd_module.Window.__init__

        def patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            try:
                alias = str(getattr(self, '_Window__viewKey', '') or
                           getattr(self, 'viewKey', '') or '')
                if 'FortVehicle' in alias:
                    BigWorld.callback(0.1, _hook)
            except Exception:
                pass

        wnd_module.Window.__init__ = patched_init
        _log('WULF hook installed')
    except Exception as e:
        _err('WULF hook error: ' + str(e))


_log('init')
_hookWulfWindows()
BigWorld.callback(3.0, _hook)
