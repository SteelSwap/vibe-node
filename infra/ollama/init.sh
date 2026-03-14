#!/bin/sh
set -e

MODEL="${EMBEDDING_MODEL:-hf.co/jinaai/jina-code-embeddings-1.5b-GGUF:Q8_0}"
EXPECTED_DIGEST="sha256:3a09a8817b852b5a4faaa6ebb1a5590322746d2b570b578d0b7e3b6e849062aa"

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
