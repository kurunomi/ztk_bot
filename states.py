from aiogram.fsm.state import State, StatesGroup


class ScheduleStates(StatesGroup):
    choosing_mode = State()            # Головне меню: розклад чи викладач
    choosing_course = State()
    choosing_group = State()
    choosing_day = State()
    choosing_teacher_letter = State()  # Вибір першої літери прізвища
    choosing_teacher = State()        # Вибір викладача зі списку
    choosing_teacher_day = State()    # Вибір дня для викладача