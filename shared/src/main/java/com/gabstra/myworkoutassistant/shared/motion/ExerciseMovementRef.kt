package com.gabstra.myworkoutassistant.shared.motion

import java.security.MessageDigest

data class ExerciseMovementRef(
    val movementId: String,
    val contentHash: String,
    val format: String = FORMAT_WEAR_SKELETON_JSON,
    val version: Int = 1,
) {
    companion object {
        const val FORMAT_WEAR_SKELETON_JSON = "wear_skeleton_json_v1"

        fun forWearSkeletonJson(movementId: String, json: String): ExerciseMovementRef {
            return ExerciseMovementRef(
                movementId = movementId,
                contentHash = contentHashFor(json),
            )
        }

        fun contentHashFor(content: String): String {
            val digest = MessageDigest.getInstance("SHA-256")
                .digest(content.toByteArray(Charsets.UTF_8))
            return digest.joinToString(separator = "") { byte -> "%02x".format(byte) }
        }
    }
}
