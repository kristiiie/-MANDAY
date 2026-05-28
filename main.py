"""
Игра «Монстры на болоте».

Условия:
- болото представляет собой квадратное поле с координатами от (0; 0) до (9; 9);
- на поле случайно размещаются четыре монстра;
- игроку даётся десять попыток;
- после каждого промаха выводятся расстояния до оставшихся монстров;
- при угадывании координат монстра попытка не тратится, игрок получает
  дополнительный ход.

Программа реализована с текстовым интерфейсом.
"""

import math
import random
from dataclasses import dataclass


FIELD_SIZE = 10
MONSTERS_COUNT = 4
ATTEMPTS_COUNT = 10


@dataclass(frozen=True)
class Point:
    """Координата клетки на игровом поле."""

    x: int
    y: int

    def distance_to(self, other: "Point") -> float:
        """
        Рассчитать расстояние до другой клетки.

        Используется расстояние по прямой между двумя точками:
        sqrt((x2 - x1)^2 + (y2 - y1)^2).
        """

        return math.sqrt((other.x - self.x) ** 2 + (other.y - self.y) ** 2)


class SwampField:
    """Игровое поле с монстрами."""

    def __init__(self, size: int, monsters_count: int) -> None:
        self.size = size
        self.monsters = self._generate_monsters(monsters_count)

    def _generate_monsters(self, monsters_count: int) -> set[Point]:
        """Случайно разместить монстров на разных клетках поля."""

        all_cells = [
            Point(x, y)
            for x in range(self.size)
            for y in range(self.size)
        ]

        return set(random.sample(all_cells, monsters_count))

    def is_inside(self, point: Point) -> bool:
        """Проверить, находится ли клетка внутри игрового поля."""

        return 0 <= point.x < self.size and 0 <= point.y < self.size

    def has_monster(self, point: Point) -> bool:
        """Проверить, есть ли монстр в указанной клетке."""

        return point in self.monsters

    def catch_monster(self, point: Point) -> bool:
        """
        Попытаться поймать монстра.

        Возвращает True, если монстр был найден и удалён с поля.
        """

        if point in self.monsters:
            self.monsters.remove(point)
            return True

        return False

    def get_distances_to_monsters(self, point: Point) -> list[float]:
        """Получить расстояния от выбранной клетки до всех оставшихся монстров."""

        distances = [
            point.distance_to(monster)
            for monster in self.monsters
        ]

        return sorted(distances)

    def monsters_left(self) -> int:
        """Получить количество оставшихся монстров."""

        return len(self.monsters)


class SwampMonstersGame:
    """Основная логика игры «Монстры на болоте»."""

    def __init__(
        self,
        field_size: int = FIELD_SIZE,
        monsters_count: int = MONSTERS_COUNT,
        attempts_count: int = ATTEMPTS_COUNT,
    ) -> None:
        self.field = SwampField(field_size, monsters_count)
        self.attempts_left = attempts_count
        self.used_points: set[Point] = set()

    def start(self) -> None:
        """Запустить игровой цикл."""

        self._print_rules()

        while self.attempts_left > 0 and self.field.monsters_left() > 0:
            print()
            print(f"Осталось попыток: {self.attempts_left}")
            print(f"Осталось монстров: {self.field.monsters_left()}")

            point = self._read_point()

            if point in self.used_points:
                print("Вы уже проверяли эту клетку. Введите другие координаты.")
                continue

            self.used_points.add(point)

            if self.field.catch_monster(point):
                print("Монстр пойман! Попытка не потрачена, вы получаете дополнительный ход.")

                if self.field.monsters_left() > 0:
                    self._print_distance_hint(point)

                continue

            self.attempts_left -= 1
            print("В этой клетке монстра нет.")

            if self.field.monsters_left() > 0:
                self._print_distance_hint(point)

        self._print_result()

    def _print_rules(self) -> None:
        """Вывести правила игры."""

        max_coordinate = self.field.size - 1

        print("Игра «Монстры на болоте»")
        print("-" * 32)
        print(f"Размер поля: {self.field.size} x {self.field.size}")
        print(f"Координаты клеток: от (0; 0) до ({max_coordinate}; {max_coordinate})")
        print(f"Количество монстров: {self.field.monsters_left()}")
        print(f"Количество попыток: {self.attempts_left}")
        print()
        print("Вводите координаты клетки, в которой может находиться монстр.")
        print("Если координаты угаданы, попытка не тратится.")
        print("После промаха программа покажет расстояния до оставшихся монстров.")
        print("-" * 32)

    def _read_point(self) -> Point:
        """Считать координаты клетки с проверкой корректности ввода."""

        while True:
            raw_x = input("Введите координату x: ").strip()
            raw_y = input("Введите координату y: ").strip()

            if not raw_x.isdigit() or not raw_y.isdigit():
                print("Ошибка: координаты должны быть целыми числами.")
                continue

            point = Point(int(raw_x), int(raw_y))

            if not self.field.is_inside(point):
                max_coordinate = self.field.size - 1
                print(f"Ошибка: координаты должны быть от 0 до {max_coordinate}.")
                continue

            return point

    def _print_distance_hint(self, point: Point) -> None:
        """Вывести подсказку с расстояниями до оставшихся монстров."""

        distances = self.field.get_distances_to_monsters(point)

        print("Расстояния до оставшихся монстров:")
        for index, distance in enumerate(distances, start=1):
            print(f"{index}) {distance:.2f}")

    def _print_result(self) -> None:
        """Вывести итог игры."""

        print()
        print("-" * 32)

        if self.field.monsters_left() == 0:
            print("Победа! Все монстры пойманы.")
            print(f"Неиспользованные попытки: {self.attempts_left}")
        else:
            print("Попытки закончились. Не все монстры были пойманы.")
            print(f"Осталось монстров: {self.field.monsters_left()}")

        print("-" * 32)


def main() -> None:
    """Точка входа в программу."""

    game = SwampMonstersGame()
    game.start()


if __name__ == "__main__":
    main()
