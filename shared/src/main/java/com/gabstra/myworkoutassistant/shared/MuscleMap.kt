package com.gabstra.myworkoutassistant.shared

import androidx.compose.ui.graphics.Path

enum class MuscleGroup {
    // Front
    PECTORALS,
    ABDOMINALS,
    OBLIQUES,
    ANTERIOR_DELTOIDS, // Front Shoulders
    BICEPS,
    FOREARMS,
    QUADRICEPS,
    TIBIALIS, // Front Calves (Shin muscles)

    // Back
    TRAPEZIUS,
    LATISSIMUS, // Lats
    POSTERIOR_DELTOIDS, // Rear Shoulders
    TRICEPS,
    GLUTES,
    HAMSTRINGS,
    CALVES, // Gastrocnemius
    ERECTORS // Lower Back
}

object MusclePathProvider {

    fun getMusclePaths(): Map<MuscleGroup, Path> {
        val map = mutableMapOf<MuscleGroup, Path>()

        // --- FRONT BODY (0 to 100 X) ---

        // Pectorals (Chest)
        map[MuscleGroup.PECTORALS] = Path().apply {
            // Left Pec
            moveTo(50f, 45f); lineTo(50f, 65f); lineTo(80f, 60f); lineTo(90f, 45f); close()
            // Right Pec
            moveTo(50f, 45f); lineTo(50f, 65f); lineTo(20f, 60f); lineTo(10f, 45f); close()
        }

        // Abdominals (Six pack)
        map[MuscleGroup.ABDOMINALS] = Path().apply {
            moveTo(40f, 65f); lineTo(60f, 65f); lineTo(58f, 100f); lineTo(42f, 100f); close()
        }

        // Obliques (Side abs)
        map[MuscleGroup.OBLIQUES] = Path().apply {
            // Left
            moveTo(60f, 65f); lineTo(70f, 70f); lineTo(65f, 95f); lineTo(58f, 100f); close()
            // Right
            moveTo(40f, 65f); lineTo(30f, 70f); lineTo(35f, 95f); lineTo(42f, 100f); close()
        }

        // Anterior Deltoids (Front Shoulder)
        map[MuscleGroup.ANTERIOR_DELTOIDS] = Path().apply {
            // Left
            moveTo(90f, 45f); lineTo(105f, 48f); lineTo(100f, 65f); lineTo(80f, 60f); close()
            // Right
            moveTo(10f, 45f); lineTo(-5f, 48f); lineTo(0f, 65f); lineTo(20f, 60f); close()
        }

        // Biceps
        map[MuscleGroup.BICEPS] = Path().apply {
            // Left
            moveTo(100f, 65f); lineTo(105f, 65f); lineTo(108f, 85f); lineTo(98f, 85f); close()
            // Right
            moveTo(0f, 65f); lineTo(-5f, 65f); lineTo(-8f, 85f); lineTo(2f, 85f); close()
        }

        // Forearms
        map[MuscleGroup.FOREARMS] = Path().apply {
            // Left
            moveTo(98f, 85f); lineTo(108f, 85f); lineTo(112f, 110f); lineTo(100f, 110f); close()
            // Right
            moveTo(2f, 85f); lineTo(-8f, 85f); lineTo(-12f, 110f); lineTo(0f, 110f); close()
        }

        // Quadriceps (Front Thighs)
        map[MuscleGroup.QUADRICEPS] = Path().apply {
            // Left
            moveTo(50f, 100f); lineTo(75f, 100f); lineTo(70f, 160f); lineTo(52f, 160f); close()
            // Right
            moveTo(50f, 100f); lineTo(25f, 100f); lineTo(30f, 160f); lineTo(48f, 160f); close()
        }

        // Tibialis (Front Shin)
        map[MuscleGroup.TIBIALIS] = Path().apply {
            // Left
            moveTo(52f, 165f); lineTo(68f, 165f); lineTo(65f, 210f); lineTo(54f, 210f); close()
            // Right
            moveTo(48f, 165f); lineTo(32f, 165f); lineTo(35f, 210f); lineTo(46f, 210f); close()
        }


        // --- BACK BODY (Offset X by 120) ---
        val ox = 120f // Offset X used to shift everything to the right

        // Trapezius (Upper Back/Neck)
        map[MuscleGroup.TRAPEZIUS] = Path().apply {
            moveTo(ox + 50f, 35f) // Neck
            lineTo(ox + 80f, 45f); lineTo(ox + 50f, 80f) // Mid back point
            lineTo(ox + 20f, 45f); close()
        }

        // Latissimus Dorsi (Lats - Wings)
        map[MuscleGroup.LATISSIMUS] = Path().apply {
            moveTo(ox + 50f, 80f)
            lineTo(ox + 80f, 65f); lineTo(ox + 75f, 100f) // Side
            lineTo(ox + 50f, 110f) // Lower spine
            lineTo(ox + 25f, 100f); lineTo(ox + 20f, 65f); close()
        }

        // Posterior Deltoids (Rear Shoulders)
        map[MuscleGroup.POSTERIOR_DELTOIDS] = Path().apply {
            // Left side of back image (which is the Left arm)
            moveTo(ox + 20f, 45f); lineTo(ox + 5f, 48f); lineTo(ox + 8f, 65f); lineTo(ox + 20f, 65f); close()
            // Right side of back image
            moveTo(ox + 80f, 45f); lineTo(ox + 95f, 48f); lineTo(ox + 92f, 65f); lineTo(ox + 80f, 65f); close()
        }

        // Triceps
        map[MuscleGroup.TRICEPS] = Path().apply {
            // Left
            moveTo(ox + 8f, 65f); lineTo(ox + 20f, 65f); lineTo(ox + 18f, 85f); lineTo(ox + 10f, 85f); close()
            // Right
            moveTo(ox + 92f, 65f); lineTo(ox + 80f, 65f); lineTo(ox + 82f, 85f); lineTo(ox + 90f, 85f); close()
        }

        // Erectors (Lower Back)
        map[MuscleGroup.ERECTORS] = Path().apply {
            moveTo(ox + 50f, 110f); lineTo(ox + 65f, 105f); lineTo(ox + 60f, 120f)
            lineTo(ox + 40f, 120f); lineTo(ox + 35f, 105f); close()
        }

        // Glutes
        map[MuscleGroup.GLUTES] = Path().apply {
            moveTo(ox + 50f, 120f)
            lineTo(ox + 75f, 120f); lineTo(ox + 75f, 145f); lineTo(ox + 50f, 145f) // Right cheek
            lineTo(ox + 25f, 145f); lineTo(ox + 25f, 120f); close() // Left cheek
        }

        // Hamstrings (Back of Thigh)
        map[MuscleGroup.HAMSTRINGS] = Path().apply {
            // Left Leg (on the back view, left is actually left)
            moveTo(ox + 48f, 145f); lineTo(ox + 28f, 145f); lineTo(ox + 32f, 200f); lineTo(ox + 46f, 200f); close()
            // Right Leg
            moveTo(ox + 52f, 145f); lineTo(ox + 72f, 145f); lineTo(ox + 68f, 200f); lineTo(ox + 54f, 200f); close()
        }

        // Calves (Back)
        map[MuscleGroup.CALVES] = Path().apply {
            // Left
            moveTo(ox + 46f, 205f); lineTo(ox + 32f, 205f); lineTo(ox + 35f, 250f); lineTo(ox + 48f, 250f); close()
            // Right
            moveTo(ox + 54f, 205f); lineTo(ox + 68f, 205f); lineTo(ox + 65f, 250f); lineTo(ox + 52f, 250f); close()
        }

        return map
    }
}