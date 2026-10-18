from quick_chat_api.core.vectorstore.sparse import encode_document, encode_query


def test_document_and_query_share_indices_and_saturate_tf() -> None:
    d_idx, d_val = encode_document("Theft theft THEFT of a vehicle")
    q_idx, q_val = encode_query("theft")

    assert q_idx[0] in d_idx
    assert q_val == [1.0]
    tf3 = d_val[d_idx.index(q_idx[0])]
    tf1 = d_val[d_idx.index(encode_query("vehicle")[0][0])]
    assert tf1 < tf3 < 3 * tf1


def test_empty_text_yields_empty_vector() -> None:
    assert encode_document("") == ([], [])
