package com.gabstra.myworkoutassistant.shared.datalayer

/**
 * Shared utilities for building and parsing DataLayer paths.
 * All paths are transaction-scoped to enable concurrent transfers.
 */
object DataLayerPaths {
    // Path prefixes (without transaction ID)
    const val SYNC_REQUEST_PREFIX = "/sync/request"
    const val SYNC_ACK_PREFIX = "/sync/ack"
    const val SYNC_COMPLETE_PREFIX = "/sync/complete"
    const val SYNC_ERROR_PREFIX = "/sync/error"
    const val WORKOUT_HISTORY_START_PREFIX = "/workoutHistory/start"
    const val WORKOUT_HISTORY_CHUNK_PREFIX = "/workoutHistory/chunk"
    const val APP_BACKUP_START_PREFIX = "/appBackup/start"
    const val APP_BACKUP_CHUNK_PREFIX = "/appBackup/chunk"
    const val WORKOUT_STORE_PREFIX = "/workoutStore"

    /**
     * Builds a transaction-scoped path.
     *
     * @param prefix The path prefix (e.g., SYNC_REQUEST_PREFIX)
     * @param transactionId The transaction ID
     * @param index Optional chunk index (for chunk paths)
     * @return The full path (e.g., "/sync/request/{transactionId}" or "/workoutHistory/chunk/{transactionId}/{index}")
     */
    fun buildPath(prefix: String, transactionId: String, index: Int? = null): String {
        return if (index != null) {
            "$prefix/$transactionId/$index"
        } else {
            "$prefix/$transactionId"
        }
    }

    /**
     * Parses the transaction ID from a path.
     *
     * @param path The full path (e.g., "/sync/request/abc-123")
     * @param prefix The expected prefix (e.g., SYNC_REQUEST_PREFIX)
     * @return The transaction ID, or null if the path doesn't match the prefix
     */
    fun parseTransactionId(path: String, prefix: String): String? {
        if (!path.startsWith(prefix)) {
            return null
        }
        
        // Remove prefix and leading slash
        val remaining = path.removePrefix(prefix).removePrefix("/")
        
        // For chunk paths, transaction ID is before the last segment (index)
        val segments = remaining.split("/")
        return when {
            segments.isEmpty() -> null
            segments.size == 1 -> segments[0] // Simple path like /sync/request/{tid}
            segments.size >= 2 -> segments[0] // Chunk path like /workoutHistory/chunk/{tid}/{index}
            else -> null
        }
    }

    /**
     * Parses the chunk index from a chunk path.
     *
     * @param path The full path (e.g., "/workoutHistory/chunk/abc-123/5")
     * @param prefix The expected prefix (e.g., WORKOUT_HISTORY_CHUNK_PREFIX)
     * @return The chunk index, or null if the path doesn't match or isn't a chunk path
     */
    fun parseChunkIndex(path: String, prefix: String): Int? {
        if (!path.startsWith(prefix)) {
            return null
        }
        
        // Remove prefix and leading slash
        val remaining = path.removePrefix(prefix).removePrefix("/")
        val segments = remaining.split("/")
        
        // For chunk paths, index is the last segment
        return if (segments.size >= 2) {
            segments.lastOrNull()?.toIntOrNull()
        } else {
            null
        }
    }

    /**
     * Checks if a path matches a prefix (for use in when statements).
     *
     * @param path The path to check
     * @param prefix The prefix to match against
     * @return True if the path starts with the prefix
     */
    fun matchesPrefix(path: String, prefix: String): Boolean {
        return path.startsWith(prefix)
    }
}
