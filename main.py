"""
Персональный ассистент по расчёту MANDAY.

Программа помогает рассчитать стоимость одного рабочего дня с учётом:
- календарных выходных;
- дополнительных нерабочих дней по производственному календарю;
- персональных выходных, отпуска и разгрузочных дней;
- годовых расходов по категориям;
- валюты расчёта;
- сценариев налогообложения РФ: НДФЛ и НПД.

Запуск:
    python main.py
"""

from __future__ import annotations

import calendar
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional


DATE_FORMAT = "%Y-%m-%d"
SAVE_FILE = Path("manday_project.json")


class TaxMode(str, Enum):
    """Поддерживаемые режимы расчёта налога."""

    NONE = "none"
    NDFL = "ndfl"
    NPD = "npd"


class NpdClientType(str, Enum):
    """Тип клиента для расчёта налога на профессиональный доход."""

    INDIVIDUAL = "individual"
    BUSINESS = "business"
    MIXED = "mixed"


@dataclass
class CurrencySettings:
    """Настройки валюты.

    rub_per_unit показывает, сколько рублей стоит одна единица выбранной валюты.
    Для рублей значение равно 1.0. Если расчёт ведётся в долларах при курсе
    90 рублей за доллар, rub_per_unit нужно указать как 90.0.
    """

    code: str = "RUB"
    symbol: str = "₽"
    rub_per_unit: float = 1.0

    def to_rub(self, amount: float) -> float:
        """Переводит сумму из выбранной валюты в рубли."""
        return amount * self.rub_per_unit

    def from_rub(self, amount: float) -> float:
        """Переводит сумму из рублей в выбранную валюту."""
        if self.rub_per_unit <= 0:
            raise ValueError("Курс валюты должен быть больше нуля.")
        return amount / self.rub_per_unit


@dataclass
class ExpenseCategory:
    """Категория расходов."""

    name: str
    annual_amount: float
    comment: str = ""


@dataclass
class NpdSettings:
    """Параметры НПД.

    Для смешанного сценария individual_share показывает долю доходов от физических
    лиц в диапазоне от 0 до 1. Остальная часть считается доходом от ИП и компаний.
    """

    client_type: NpdClientType = NpdClientType.BUSINESS
    individual_share: float = 0.0


@dataclass
class ProjectData:
    """Все данные проекта расчёта."""

    year: int = field(default_factory=lambda: date.today().year)
    currency: CurrencySettings = field(default_factory=CurrencySettings)
    official_non_working_dates: list[str] = field(default_factory=list)
    personal_non_working_dates: list[str] = field(default_factory=list)
    expenses: list[ExpenseCategory] = field(default_factory=list)
    tax_mode: TaxMode = TaxMode.NONE
    npd_settings: NpdSettings = field(default_factory=NpdSettings)
    planned_daily_rate: float = 0.0


@dataclass
class CalculationResult:
    """Итоги расчёта."""

    days_in_year: int
    weekend_days: int
    official_days: int
    personal_days: int
    non_working_days: int
    working_days: int
    annual_expenses: float
    base_manday: float
    required_gross_annual_income: float
    required_gross_manday: float
    tax_amount: float
    net_income_after_tax: float
    planned_gross_annual_income: float
    planned_tax_amount: float
    planned_net_income: float
    planned_balance: float
    warnings: list[str]


class MandayCalculator:
    """Выполняет расчёт рабочих дней, MANDAY и налоговых сценариев."""

    NPD_LIMIT_RUB = 2_400_000.0
    NPD_INDIVIDUAL_RATE = 0.04
    NPD_BUSINESS_RATE = 0.06

    # Прогрессивная шкала НДФЛ для основных доходов налоговых резидентов РФ
    # с 2025 года. Налог начисляется по ступеням: повышенная ставка применяется
    # только к части дохода сверх предыдущего порога.
    NDFL_BRACKETS = [
        (2_400_000.0, 0.13),
        (5_000_000.0, 0.15),
        (20_000_000.0, 0.18),
        (50_000_000.0, 0.20),
        (float("inf"), 0.22),
    ]

    def __init__(self, data: ProjectData) -> None:
        self.data = data

    def calculate(self) -> CalculationResult:
        """Возвращает полный результат расчёта."""
        warnings: list[str] = []
        all_weekends = self._weekend_dates(self.data.year)
        official_dates = self._parse_dates(self.data.official_non_working_dates)
        personal_dates = self._parse_dates(self.data.personal_non_working_dates)

        official_workday_dates = official_dates - all_weekends
        personal_workday_dates = personal_dates - all_weekends - official_workday_dates
        non_working_dates = all_weekends | official_dates | personal_dates

        days_in_year = 366 if calendar.isleap(self.data.year) else 365
        working_days = days_in_year - len(non_working_dates)

        if working_days <= 0:
            raise ValueError("Количество рабочих дней должно быть больше нуля.")

        annual_expenses = sum(item.annual_amount for item in self.data.expenses)
        base_manday = annual_expenses / working_days

        annual_expenses_rub = self.data.currency.to_rub(annual_expenses)
        required_gross_annual_income_rub = self._gross_income_for_target_net(
            target_net_rub=annual_expenses_rub,
            tax_mode=self.data.tax_mode,
        )
        tax_amount_rub = self._calculate_tax(
            gross_income_rub=required_gross_annual_income_rub,
            tax_mode=self.data.tax_mode,
        )
        net_income_after_tax_rub = required_gross_annual_income_rub - tax_amount_rub

        required_gross_annual_income = self.data.currency.from_rub(
            required_gross_annual_income_rub
        )
        required_gross_manday = required_gross_annual_income / working_days
        tax_amount = self.data.currency.from_rub(tax_amount_rub)
        net_income_after_tax = self.data.currency.from_rub(net_income_after_tax_rub)

        planned_gross_annual_income = self.data.planned_daily_rate * working_days
        planned_gross_annual_income_rub = self.data.currency.to_rub(
            planned_gross_annual_income
        )
        planned_tax_amount_rub = self._calculate_tax(
            gross_income_rub=planned_gross_annual_income_rub,
            tax_mode=self.data.tax_mode,
        )
        planned_net_income_rub = planned_gross_annual_income_rub - planned_tax_amount_rub
        planned_net_income = self.data.currency.from_rub(planned_net_income_rub)
        planned_tax_amount = self.data.currency.from_rub(planned_tax_amount_rub)
        planned_balance = planned_net_income - annual_expenses

        if self.data.tax_mode == TaxMode.NPD:
            if required_gross_annual_income_rub > self.NPD_LIMIT_RUB:
                warnings.append(
                    "Для покрытия расходов требуемый годовой доход превышает "
                    "лимит НПД 2 400 000 ₽. НПД может быть неприменим."
                )
            if planned_gross_annual_income_rub > self.NPD_LIMIT_RUB:
                warnings.append(
                    "Плановый доход по выбранному дневному тарифу превышает "
                    "лимит НПД 2 400 000 ₽."
                )

        return CalculationResult(
            days_in_year=days_in_year,
            weekend_days=len(all_weekends),
            official_days=len(official_workday_dates),
            personal_days=len(personal_workday_dates),
            non_working_days=len(non_working_dates),
            working_days=working_days,
            annual_expenses=annual_expenses,
            base_manday=base_manday,
            required_gross_annual_income=required_gross_annual_income,
            required_gross_manday=required_gross_manday,
            tax_amount=tax_amount,
            net_income_after_tax=net_income_after_tax,
            planned_gross_annual_income=planned_gross_annual_income,
            planned_tax_amount=planned_tax_amount,
            planned_net_income=planned_net_income,
            planned_balance=planned_balance,
            warnings=warnings,
        )

    def _weekend_dates(self, year: int) -> set[date]:
        """Возвращает все субботы и воскресенья указанного года."""
        current = date(year, 1, 1)
        last = date(year, 12, 31)
        weekends: set[date] = set()
        while current <= last:
            if current.weekday() >= 5:
                weekends.add(current)
            current += timedelta(days=1)
        return weekends

    def _parse_dates(self, values: Iterable[str]) -> set[date]:
        """Преобразует строки дат в объекты date."""
        result: set[date] = set()
        for value in values:
            try:
                item = datetime.strptime(value, DATE_FORMAT).date()
            except ValueError:
                continue
            if item.year == self.data.year:
                result.add(item)
        return result

    def _calculate_tax(self, gross_income_rub: float, tax_mode: TaxMode) -> float:
        """Рассчитывает сумму налога в рублях."""
        if gross_income_rub <= 0 or tax_mode == TaxMode.NONE:
            return 0.0
        if tax_mode == TaxMode.NPD:
            return gross_income_rub * self._npd_effective_rate()
        if tax_mode == TaxMode.NDFL:
            return self._calculate_ndfl(gross_income_rub)
        raise ValueError(f"Неизвестный налоговый режим: {tax_mode}")

    def _calculate_ndfl(self, gross_income_rub: float) -> float:
        """Рассчитывает НДФЛ по прогрессивной шкале."""
        tax = 0.0
        previous_limit = 0.0
        for current_limit, rate in self.NDFL_BRACKETS:
            taxable_part = min(gross_income_rub, current_limit) - previous_limit
            if taxable_part > 0:
                tax += taxable_part * rate
            if gross_income_rub <= current_limit:
                break
            previous_limit = current_limit
        return tax

    def _npd_effective_rate(self) -> float:
        """Возвращает эффективную ставку НПД."""
        settings = self.data.npd_settings
        if settings.client_type == NpdClientType.INDIVIDUAL:
            return self.NPD_INDIVIDUAL_RATE
        if settings.client_type == NpdClientType.BUSINESS:
            return self.NPD_BUSINESS_RATE
        individual_share = min(max(settings.individual_share, 0.0), 1.0)
        business_share = 1.0 - individual_share
        return (
            individual_share * self.NPD_INDIVIDUAL_RATE
            + business_share * self.NPD_BUSINESS_RATE
        )

    def _gross_income_for_target_net(
        self,
        target_net_rub: float,
        tax_mode: TaxMode,
    ) -> float:
        """Находит валовый доход, который нужен для получения целевой чистой суммы."""
        if target_net_rub <= 0:
            return 0.0
        if tax_mode == TaxMode.NONE:
            return target_net_rub
        if tax_mode == TaxMode.NPD:
            rate = self._npd_effective_rate()
            return target_net_rub / (1.0 - rate)

        # Для НДФЛ используется бинарный поиск, потому что ставка прогрессивная.
        left = target_net_rub
        right = target_net_rub * 1.5 + 1_000.0
        while right - self._calculate_ndfl(right) < target_net_rub:
            right *= 2

        for _ in range(100):
            middle = (left + right) / 2
            net = middle - self._calculate_ndfl(middle)
            if net < target_net_rub:
                left = middle
            else:
                right = middle
        return right


def load_default_ru_holidays(year: int) -> list[str]:
    """Возвращает базовый набор праздничных дат РФ.

    Набор помогает быстро заполнить проект, но не заменяет официальный
    производственный календарь с переносами выходных дней. Перенесённые выходные
    можно добавить вручную через меню редактирования дат.
    """
    fixed_dates = [
        (1, 1),
        (1, 2),
        (1, 3),
        (1, 4),
        (1, 5),
        (1, 6),
        (1, 7),
        (1, 8),
        (2, 23),
        (3, 8),
        (5, 1),
        (5, 9),
        (6, 12),
        (11, 4),
    ]
    return [date(year, month, day).strftime(DATE_FORMAT) for month, day in fixed_dates]


class ConsoleUI:
    """Консольный интерфейс программы."""

    def __init__(self) -> None:
        self.data = ProjectData()

    def run(self) -> None:
        """Запускает основной цикл приложения."""
        self._print_header()
        while True:
            print("\nГлавное меню")
            print("1. Создать новый расчёт")
            print("2. Показать текущий расчёт")
            print("3. Редактировать данные")
            print("4. Сохранить данные в JSON")
            print("5. Загрузить данные из JSON")
            print("0. Выход")
            choice = input_choice("Выберите действие: ", {"1", "2", "3", "4", "5", "0"})

            if choice == "1":
                self._create_project()
            elif choice == "2":
                self._show_result()
            elif choice == "3":
                self._edit_menu()
            elif choice == "4":
                self._save_to_json()
            elif choice == "5":
                self._load_from_json()
            elif choice == "0":
                print("Работа программы завершена.")
                break

    def _print_header(self) -> None:
        """Печатает заголовок приложения."""
        print("=" * 72)
        print("Персональный ассистент по расчёту MANDAY")
        print("=" * 72)
        print(
            "MANDAY рассчитывается как годовые расходы, разделённые на "
            "количество рабочих дней."
        )

    def _create_project(self) -> None:
        """Пошагово создаёт новый проект расчёта."""
        print("\nСоздание нового расчёта")
        self.data = ProjectData()
        self._edit_year()
        self._edit_currency()
        use_defaults = input_yes_no(
            "Добавить базовые праздничные даты РФ без переносов? [д/н]: "
        )
        if use_defaults:
            self.data.official_non_working_dates = load_default_ru_holidays(self.data.year)
        self._edit_dates(date_type="official")
        self._edit_dates(date_type="personal")
        self._edit_expenses()
        self._edit_tax_settings()
        self._edit_planned_rate()
        self._show_result()

    def _edit_menu(self) -> None:
        """Показывает меню редактирования уже введённых данных."""
        while True:
            print("\nРедактирование данных")
            print("1. Год расчёта")
            print("2. Валюта")
            print("3. Нерабочие даты по производственному календарю")
            print("4. Персональные нерабочие даты")
            print("5. Категории расходов")
            print("6. Налоговый режим")
            print("7. Плановая ставка за день")
            print("8. Показать результат")
            print("0. Назад")
            choice = input_choice("Выберите действие: ", {"1", "2", "3", "4", "5", "6", "7", "8", "0"})

            if choice == "1":
                self._edit_year()
            elif choice == "2":
                self._edit_currency()
            elif choice == "3":
                self._edit_dates(date_type="official")
            elif choice == "4":
                self._edit_dates(date_type="personal")
            elif choice == "5":
                self._edit_expenses()
            elif choice == "6":
                self._edit_tax_settings()
            elif choice == "7":
                self._edit_planned_rate()
            elif choice == "8":
                self._show_result()
            elif choice == "0":
                break

    def _edit_year(self) -> None:
        """Редактирует календарный год."""
        self.data.year = input_int(
            "Введите календарный год расчёта: ",
            min_value=1900,
            max_value=2100,
            default=self.data.year,
        )
        self.data.official_non_working_dates = filter_dates_by_year(
            self.data.official_non_working_dates,
            self.data.year,
        )
        self.data.personal_non_working_dates = filter_dates_by_year(
            self.data.personal_non_working_dates,
            self.data.year,
        )

    def _edit_currency(self) -> None:
        """Редактирует валюту расчёта."""
        print("\nНастройка валюты")
        print("1. Российский рубль")
        print("2. Доллар США")
        print("3. Евро")
        print("4. Другая валюта")
        choice = input_choice("Выберите валюту: ", {"1", "2", "3", "4"})
        if choice == "1":
            self.data.currency = CurrencySettings(code="RUB", symbol="₽", rub_per_unit=1.0)
        elif choice == "2":
            rate = input_float("Введите курс: сколько рублей стоит 1 USD: ", min_value=0.01)
            self.data.currency = CurrencySettings(code="USD", symbol="$", rub_per_unit=rate)
        elif choice == "3":
            rate = input_float("Введите курс: сколько рублей стоит 1 EUR: ", min_value=0.01)
            self.data.currency = CurrencySettings(code="EUR", symbol="€", rub_per_unit=rate)
        else:
            code = input_non_empty("Введите код валюты, например KZT: ").upper()
            symbol = input_non_empty("Введите символ валюты: ")
            rate = input_float(
                f"Введите курс: сколько рублей стоит 1 {code}: ",
                min_value=0.01,
            )
            self.data.currency = CurrencySettings(code=code, symbol=symbol, rub_per_unit=rate)

    def _edit_dates(self, date_type: str) -> None:
        """Редактирует списки нерабочих дат."""
        if date_type == "official":
            title = "нерабочие даты по производственному календарю"
            target = self.data.official_non_working_dates
        else:
            title = "персональные нерабочие даты"
            target = self.data.personal_non_working_dates

        while True:
            print(f"\nРедактирование: {title}")
            print_dates(target)
            print("1. Добавить дату")
            print("2. Добавить диапазон дат")
            print("3. Удалить дату")
            print("4. Очистить список")
            print("0. Назад")
            choice = input_choice("Выберите действие: ", {"1", "2", "3", "4", "0"})

            if choice == "1":
                value = input_date_string("Введите дату в формате ГГГГ-ММ-ДД: ", self.data.year)
                if value not in target:
                    target.append(value)
                    target.sort()
            elif choice == "2":
                start = input_date("Дата начала диапазона: ", self.data.year)
                end = input_date("Дата окончания диапазона: ", self.data.year)
                if end < start:
                    start, end = end, start
                current = start
                while current <= end:
                    value = current.strftime(DATE_FORMAT)
                    if value not in target:
                        target.append(value)
                    current += timedelta(days=1)
                target.sort()
            elif choice == "3":
                value = input_date_string("Введите дату для удаления: ", self.data.year)
                if value in target:
                    target.remove(value)
                else:
                    print("Такой даты нет в списке.")
            elif choice == "4":
                target.clear()
            elif choice == "0":
                break

    def _edit_expenses(self) -> None:
        """Редактирует категории расходов."""
        while True:
            print("\nКатегории расходов")
            if not self.data.expenses:
                print("Список расходов пуст.")
            else:
                for index, item in enumerate(self.data.expenses, start=1):
                    print(
                        f"{index}. {item.name}: "
                        f"{format_money(item.annual_amount, self.data.currency)} "
                        f"в год; {item.comment}"
                    )
            print("1. Добавить категорию")
            print("2. Изменить категорию")
            print("3. Удалить категорию")
            print("4. Добавить демонстрационный набор расходов")
            print("0. Назад")
            choice = input_choice("Выберите действие: ", {"1", "2", "3", "4", "0"})

            if choice == "1":
                self.data.expenses.append(self._input_expense())
            elif choice == "2":
                if not self.data.expenses:
                    print("Сначала добавьте хотя бы одну категорию.")
                    continue
                index = input_int("Введите номер категории: ", 1, len(self.data.expenses)) - 1
                self.data.expenses[index] = self._input_expense()
            elif choice == "3":
                if not self.data.expenses:
                    print("Список расходов пуст.")
                    continue
                index = input_int("Введите номер категории: ", 1, len(self.data.expenses)) - 1
                removed = self.data.expenses.pop(index)
                print(f"Удалена категория: {removed.name}")
            elif choice == "4":
                self._add_demo_expenses()
            elif choice == "0":
                break

    def _input_expense(self) -> ExpenseCategory:
        """Запрашивает одну категорию расходов."""
        name = input_non_empty("Название категории: ")
        print("Периодичность расхода")
        print("1. Ежемесячно")
        print("2. Ежегодно")
        print("3. Разовый расход в течение года")
        choice = input_choice("Выберите периодичность: ", {"1", "2", "3"})
        amount = input_float("Сумма за выбранный период: ", min_value=0.0)
        if choice == "1":
            annual_amount = amount * 12
            comment = "ежемесячный расход"
        elif choice == "2":
            annual_amount = amount
            comment = "ежегодный расход"
        else:
            annual_amount = amount
            comment = "разовый расход"
        extra_comment = input("Комментарий, можно оставить пустым: ").strip()
        if extra_comment:
            comment = f"{comment}; {extra_comment}"
        return ExpenseCategory(name=name, annual_amount=annual_amount, comment=comment)

    def _add_demo_expenses(self) -> None:
        """Добавляет пример расходов для быстрого тестирования."""
        self.data.expenses = [
            ExpenseCategory("Аренда жилья и коммунальные платежи", 55_000 * 12, "ежемесячно"),
            ExpenseCategory("Питание и бытовые расходы", 35_000 * 12, "ежемесячно"),
            ExpenseCategory("Транспорт", 7_000 * 12, "ежемесячно"),
            ExpenseCategory("Связь, интернет и подписки", 5_000 * 12, "ежемесячно"),
            ExpenseCategory("Отпуск", 180_000, "ежегодно"),
            ExpenseCategory("Обновление техники", 150_000, "разовый желаемый расход"),
            ExpenseCategory("Резерв и накопления", 300_000, "финансовая подушка"),
        ]
        print("Демонстрационный набор расходов добавлен.")

    def _edit_tax_settings(self) -> None:
        """Редактирует налоговый режим."""
        print("\nНалоговый режим")
        print("1. Без налога")
        print("2. НДФЛ")
        print("3. НПД")
        choice = input_choice("Выберите налоговый режим: ", {"1", "2", "3"})
        if choice == "1":
            self.data.tax_mode = TaxMode.NONE
        elif choice == "2":
            self.data.tax_mode = TaxMode.NDFL
        else:
            self.data.tax_mode = TaxMode.NPD
            self._edit_npd_settings()

    def _edit_npd_settings(self) -> None:
        """Редактирует параметры НПД."""
        print("\nНастройка НПД")
        print("1. Все клиенты — физические лица, ставка 4%")
        print("2. Все клиенты — ИП и организации, ставка 6%")
        print("3. Смешанный поток клиентов")
        choice = input_choice("Выберите тип клиентов: ", {"1", "2", "3"})
        if choice == "1":
            self.data.npd_settings = NpdSettings(NpdClientType.INDIVIDUAL, 1.0)
        elif choice == "2":
            self.data.npd_settings = NpdSettings(NpdClientType.BUSINESS, 0.0)
        else:
            share_percent = input_float(
                "Введите долю дохода от физических лиц в процентах: ",
                min_value=0.0,
                max_value=100.0,
            )
            self.data.npd_settings = NpdSettings(
                NpdClientType.MIXED,
                share_percent / 100.0,
            )

    def _edit_planned_rate(self) -> None:
        """Редактирует плановую дневную ставку."""
        self.data.planned_daily_rate = input_float(
            "Введите плановую ставку за один рабочий день. "
            "Можно указать 0, если сценарий не нужен: ",
            min_value=0.0,
            default=self.data.planned_daily_rate,
        )

    def _show_result(self) -> None:
        """Показывает расчёт в консоли."""
        try:
            result = MandayCalculator(self.data).calculate()
        except ValueError as error:
            print(f"Ошибка расчёта: {error}")
            return

        currency = self.data.currency
        print("\n" + "=" * 72)
        print("ИТОГОВЫЙ РАСЧЁТ MANDAY")
        print("=" * 72)
        print(f"Год: {self.data.year}")
        print(
            f"Валюта: {currency.code}; курс для налогового блока: "
            f"1 {currency.code} = {currency.rub_per_unit:.4f} ₽"
        )
        print("\nРабочее время")
        print(f"Дней в году: {result.days_in_year}")
        print(f"Календарных выходных: {result.weekend_days}")
        print(f"Дополнительных нерабочих дней по календарю: {result.official_days}")
        print(f"Персональных нерабочих дней: {result.personal_days}")
        print(f"Всего нерабочих дней: {result.non_working_days}")
        print(f"Рабочих дней: {result.working_days}")

        print("\nРасходы")
        if self.data.expenses:
            for item in self.data.expenses:
                print(f"- {item.name}: {format_money(item.annual_amount, currency)}")
        else:
            print("Расходы не введены.")
        print(f"Годовые расходы: {format_money(result.annual_expenses, currency)}")
        print(f"Базовый MANDAY без налоговой надбавки: {format_money(result.base_manday, currency)}")

        print("\nНалоговый сценарий")
        print(f"Режим: {tax_mode_title(self.data.tax_mode)}")
        print(
            "Требуемый валовый доход для покрытия расходов после налога: "
            f"{format_money(result.required_gross_annual_income, currency)}"
        )
        print(f"Оценка налога: {format_money(result.tax_amount, currency)}")
        print(
            "Чистый доход после налога: "
            f"{format_money(result.net_income_after_tax, currency)}"
        )
        print(
            "MANDAY с учётом выбранного налогового режима: "
            f"{format_money(result.required_gross_manday, currency)}"
        )

        if self.data.planned_daily_rate > 0:
            print("\nСценарий по плановой дневной ставке")
            print(f"Плановая ставка: {format_money(self.data.planned_daily_rate, currency)}")
            print(
                "Годовой доход до налога: "
                f"{format_money(result.planned_gross_annual_income, currency)}"
            )
            print(f"Налог: {format_money(result.planned_tax_amount, currency)}")
            print(f"Доход после налога: {format_money(result.planned_net_income, currency)}")
            print(f"Баланс после расходов: {format_money(result.planned_balance, currency)}")

        if result.warnings:
            print("\nПредупреждения")
            for warning in result.warnings:
                print(f"! {warning}")
        print("=" * 72)

    def _save_to_json(self) -> None:
        """Сохраняет проект в JSON-файл."""
        payload = asdict(self.data)
        payload["tax_mode"] = self.data.tax_mode.value
        payload["npd_settings"]["client_type"] = self.data.npd_settings.client_type.value
        SAVE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Данные сохранены в файл {SAVE_FILE.resolve()}")

    def _load_from_json(self) -> None:
        """Загружает проект из JSON-файла."""
        if not SAVE_FILE.exists():
            print(f"Файл {SAVE_FILE} не найден.")
            return
        payload = json.loads(SAVE_FILE.read_text(encoding="utf-8"))
        self.data = project_data_from_dict(payload)
        print("Данные загружены.")
        self._show_result()


def project_data_from_dict(payload: dict) -> ProjectData:
    """Восстанавливает ProjectData из словаря."""
    currency_payload = payload.get("currency", {})
    npd_payload = payload.get("npd_settings", {})
    expenses_payload = payload.get("expenses", [])
    return ProjectData(
        year=int(payload.get("year", date.today().year)),
        currency=CurrencySettings(
            code=str(currency_payload.get("code", "RUB")),
            symbol=str(currency_payload.get("symbol", "₽")),
            rub_per_unit=float(currency_payload.get("rub_per_unit", 1.0)),
        ),
        official_non_working_dates=list(payload.get("official_non_working_dates", [])),
        personal_non_working_dates=list(payload.get("personal_non_working_dates", [])),
        expenses=[
            ExpenseCategory(
                name=str(item.get("name", "Без названия")),
                annual_amount=float(item.get("annual_amount", 0.0)),
                comment=str(item.get("comment", "")),
            )
            for item in expenses_payload
        ],
        tax_mode=TaxMode(payload.get("tax_mode", TaxMode.NONE.value)),
        npd_settings=NpdSettings(
            client_type=NpdClientType(npd_payload.get("client_type", NpdClientType.BUSINESS.value)),
            individual_share=float(npd_payload.get("individual_share", 0.0)),
        ),
        planned_daily_rate=float(payload.get("planned_daily_rate", 0.0)),
    )


def filter_dates_by_year(values: list[str], year: int) -> list[str]:
    """Оставляет в списке только даты нужного года."""
    result = []
    for value in values:
        try:
            parsed = datetime.strptime(value, DATE_FORMAT).date()
        except ValueError:
            continue
        if parsed.year == year:
            result.append(value)
    return sorted(set(result))


def input_choice(prompt: str, allowed: set[str]) -> str:
    """Запрашивает выбор из набора допустимых строк."""
    while True:
        value = input(prompt).strip()
        if value in allowed:
            return value
        print(f"Введите одно из значений: {', '.join(sorted(allowed))}.")


def input_non_empty(prompt: str) -> str:
    """Запрашивает непустую строку."""
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Значение не должно быть пустым.")


def input_yes_no(prompt: str) -> bool:
    """Запрашивает ответ да/нет."""
    while True:
        value = input(prompt).strip().lower()
        if value in {"д", "да", "y", "yes"}:
            return True
        if value in {"н", "нет", "n", "no"}:
            return False
        print("Введите 'д' или 'н'.")


def input_int(
    prompt: str,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    default: Optional[int] = None,
) -> int:
    """Запрашивает целое число."""
    while True:
        raw_value = input(prompt_with_default(prompt, default)).strip()
        if raw_value == "" and default is not None:
            return default
        try:
            value = int(raw_value)
        except ValueError:
            print("Введите целое число.")
            continue
        if min_value is not None and value < min_value:
            print(f"Значение должно быть не меньше {min_value}.")
            continue
        if max_value is not None and value > max_value:
            print(f"Значение должно быть не больше {max_value}.")
            continue
        return value


def input_float(
    prompt: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    default: Optional[float] = None,
) -> float:
    """Запрашивает вещественное число."""
    while True:
        raw_value = input(prompt_with_default(prompt, default)).strip().replace(",", ".")
        if raw_value == "" and default is not None:
            return default
        try:
            value = float(raw_value)
        except ValueError:
            print("Введите число.")
            continue
        if min_value is not None and value < min_value:
            print(f"Значение должно быть не меньше {min_value}.")
            continue
        if max_value is not None and value > max_value:
            print(f"Значение должно быть не больше {max_value}.")
            continue
        return value


def prompt_with_default(prompt: str, default: object | None) -> str:
    """Добавляет значение по умолчанию к приглашению ввода."""
    if default is None:
        return prompt
    return f"{prompt}[по умолчанию: {default}] "


def input_date(prompt: str, expected_year: int) -> date:
    """Запрашивает дату."""
    while True:
        raw_value = input(prompt).strip()
        try:
            value = datetime.strptime(raw_value, DATE_FORMAT).date()
        except ValueError:
            print("Введите дату в формате ГГГГ-ММ-ДД.")
            continue
        if value.year != expected_year:
            print(f"Дата должна относиться к году {expected_year}.")
            continue
        return value


def input_date_string(prompt: str, expected_year: int) -> str:
    """Запрашивает дату и возвращает строку."""
    return input_date(prompt, expected_year).strftime(DATE_FORMAT)


def print_dates(values: list[str]) -> None:
    """Печатает список дат."""
    if not values:
        print("Список дат пуст.")
        return
    print("Текущие даты:")
    for value in sorted(values):
        print(f"- {value}")


def format_money(amount: float, currency: CurrencySettings) -> str:
    """Форматирует денежную сумму."""
    formatted = f"{amount:,.2f}".replace(",", " ")
    return f"{formatted} {currency.symbol}"


def tax_mode_title(mode: TaxMode) -> str:
    """Возвращает русское название налогового режима."""
    if mode == TaxMode.NONE:
        return "без налога"
    if mode == TaxMode.NDFL:
        return "НДФЛ"
    if mode == TaxMode.NPD:
        return "НПД"
    return str(mode)


def main() -> None:
    """Точка входа в программу."""
    ConsoleUI().run()


if __name__ == "__main__":
    main()
