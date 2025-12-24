def get_all_sub_things_recusively(thing) -> list:
    """get all sub things recursively from a thing"""
    sub_things = [thing]
    for sub_thing in thing.sub_things.values():
        sub_things.extend(get_all_sub_things_recusively(sub_thing))
    return sub_things
