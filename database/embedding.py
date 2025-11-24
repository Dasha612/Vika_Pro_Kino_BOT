from sentence_transformers import SentenceTransformer
model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")


def build_movie_text(info: dict) -> str:
    parts = [
        info.get("title") or "",
        info.get("original_title") or "",
        info.get("overview") or "",
        ", ".join(info.get("genres") or []),
        ", ".join(info.get("keywords") or []),
    ]
    return "\n".join(p for p in parts if p.strip())
