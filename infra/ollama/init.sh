#!/bin/sh
set -e

MODEL="${EMBEDDING_MODEL:-unclemusclez/jina-embeddings-v2-base-code}"
EXPECTED_DIGEST="sha256:33a8a1b6a1cbba662f292d32bb55f8d109c0e6cb02de2d243a1b70705ea20986"

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
