EPISODE_TITLES = {
    1: 'Dio the Invader',
    2: 'A Letter from the Past',
    3: 'The Youthful Knight',
    4: 'Overdrive',
    5: 'The Dark Knights',
    6: 'The Courage to Face Death',
    7: 'The Girl with the Blue Rose',
    8: 'Bloody Battle! JoJo & Dio',
    9: 'The Final Hamon',
    10: "New York's JoJo",
    11: 'The Game Master',
    12: 'The Warrior of the Colosseum',
    13: 'JoJo vs. The Ultimate Lifeform',
    14: 'The Ultimate Warrior',
    15: "The Warrior's Repose",
    16: "Lisa Lisa's Secret",
    17: 'The Final Lesson',
    18: 'The Ties That Bind',
    19: 'The Warrior of Light',
    20: 'The Ultimate Being',
    21: 'The Birth of a Superbeing',
    22: 'The Final Battle',
    23: 'The Man Who Conquered the Sun',
    24: 'The Rise of the Superbeing',
    25: "The Warrior's Farewell",
    26: 'To the Future',
}


def part_for(ep):
    return 'Phantom Blood' if ep <= 9 else 'Battle Tendency'


def display_name(ep):
    part = part_for(ep)
    if ep <= 9:
        label = f'Episode {ep:02d}'
    else:
        label = f'Episode {ep:02d}'
    return f'{part} - {label}: {EPISODE_TITLES[ep]}'
