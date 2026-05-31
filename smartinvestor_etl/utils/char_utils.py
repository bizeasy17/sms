import pypinyin


def pinyin(word):
    """
    返回中文拼音（无分隔）
    """
    return ''.join(''.join(item) for item in pypinyin.pinyin(word, style=pypinyin.NORMAL))


def pinyin_firstletter(text):
    """
    返回中文输入文本的拼音首字母
    """
    return ''.join(pinyin(char)[0] for char in text)
