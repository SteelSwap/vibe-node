# Software Transactional Memory

Python STM implementation — optimistic concurrency with automatic retry for shared state consistency across threads.

Used by the forge loop to read tip + nonce + stake atomically, and by the peer manager / chain follower for thread-safe access to ChainDB state.

::: vibe.core.stm
    options:
      show_source: false
      members_order: source
