from aiogram.fsm.state import State, StatesGroup


class ScheduleStates(StatesGroup):
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()