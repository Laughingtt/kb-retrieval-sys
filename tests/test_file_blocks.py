from kb_retrieval.kb.ingest.wiki.file_blocks import parse_file_blocks


def test_parse_two_blocks():
    text = (
        "---FILE: wiki/sources/a.md---\n"
        "type: source\n---\nbody A\n"
        "---END FILE---\n"
        "---FILE: wiki/entities/b.md---\n"
        "type: entity\n---\nbody B\n"
        "---END FILE---\n"
    )
    blocks = parse_file_blocks(text)
    assert len(blocks) == 2
    assert blocks[0] == ("wiki/sources/a.md", "type: source\n---\nbody A\n")
    assert blocks[1] == ("wiki/entities/b.md", "type: entity\n---\nbody B\n")


def test_truncated_block_dropped():
    # 末尾 block 未闭合（无 ---END FILE---）→ 丢弃，前一个保留
    text = (
        "---FILE: wiki/sources/a.md---\n"
        "body A\n"
        "---END FILE---\n"
        "---FILE: wiki/entities/b.md---\n"
        "body B truncated without end"
    )
    blocks = parse_file_blocks(text)
    assert len(blocks) == 1
    assert blocks[0][0] == "wiki/sources/a.md"


def test_unsafe_path_dropped():
    text = (
        "---FILE: wiki/../etc/passwd.md---\n"
        "evil\n"
        "---END FILE---\n"
    )
    assert parse_file_blocks(text) == []


def test_empty_text():
    assert parse_file_blocks("") == []
