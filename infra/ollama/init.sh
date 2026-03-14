#!/bin/sh
set -e

MODEL="${EMBEDDING_MODEL:-hf.co/jinaai/jina-code-embeddings-0.5b-GGUF:Q8_0}"
EXPECTED_DIGEST="sha256:2f8aa3f34f1fae493ff9f6f7894ca7ba390b0d9a58fa0b4e65709a041beb0dc5"

echo "=== Ollama Model Init ==="
echo "Model:           $MODEL"
echo "Expected digest: $EXPECTED_DIGEST"
echo ""

# Pull the model
ollama pull "$MODEL"

# Verify the model weights hash matches
ACTUAL_DIGEST=$(ollama show "$MODEL" --modelfile 2>/dev/null | grep "^FROM " | grep -o "sha256-[a-f0-9]*" | sed 's/sha256-/sha256:/')

if [ "$ACTUAL_DIGEST" = "$EXPECTED_DIGEST" ]; then
    echo ""
    echo "=== Model verified ==="
    echo "Digest matches: $ACTUAL_DIGEST"
else
    echo ""
    echo "!!! WARNING: Model digest mismatch !!!"
    echo "Expected: $EXPECTED_DIGEST"
    echo "Got:      $ACTUAL_DIGEST"
    echo ""
    echo "The model may have been updated upstream."
    echo "Update the expected digest in infra/ollama/init.sh if intentional."
    exit 1
fi
