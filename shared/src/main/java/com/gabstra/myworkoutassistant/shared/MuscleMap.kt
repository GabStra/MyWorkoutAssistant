package com.gabstra.myworkoutassistant.shared

import androidx.compose.ui.graphics.Path

enum class MuscleGroup {
    // --- Front ---
    PECTORALS,
    ABDOMINALS,
    OBLIQUES,
    SERRATUS_ANTERIOR, // New (Ribs)
    TRAPEZIUS_FRONT,   // New (Neck/Shrug muscles visible from front)

    ANTERIOR_DELTOIDS, // Front Shoulder
    MIDDLE_DELTOIDS,   // New (Side Shoulder)

    BICEPS,
    FOREARMS,

    QUADRICEPS,
    ADDUCTORS,         // New (Inner Thigh)
    TIBIALIS,

    // --- Back ---
    TRAPEZIUS,         // Upper Back
    LATISSIMUS,
    ERECTORS,          // Lower Back

    POSTERIOR_DELTOIDS,
    TRICEPS,

    GLUTES,
    ABDUCTORS,         // New (Outer Hip/Glute Medius)
    HAMSTRINGS,
    CALVES
}

object MusclePathProvider {

    fun getMusclePaths(): Map<MuscleGroup, Path> {
        val map = mutableMapOf<MuscleGroup, Path>()

        // ===========================================
        // FRONT BODY (Center X = 50)
        // ===========================================

        // 1. Traps (Front View - neck to shoulder connection)
        map[MuscleGroup.TRAPEZIUS_FRONT] = Path().apply {
            // Left
            moveTo(50f, 35f); lineTo(65f, 35f); lineTo(80f, 45f); lineTo(50f, 40f); close()
            // Right
            moveTo(50f, 35f); lineTo(35f, 35f); lineTo(20f, 45f); lineTo(50f, 40f); close()
        }

        // 2. Middle Deltoids (Side cap of the shoulder)
        map[MuscleGroup.MIDDLE_DELTOIDS] = Path().apply {
            // Left
            moveTo(105f, 48f); lineTo(115f, 55f); lineTo(105f, 70f); lineTo(100f, 65f); close()
            // Right
            moveTo(-5f, 48f); lineTo(-15f, 55f); lineTo(-5f, 70f); lineTo(0f, 65f); close()
        }

        // 3. Anterior Deltoids (Front Shoulder)
        map[MuscleGroup.ANTERIOR_DELTOIDS] = Path().apply {
            // Left
            moveTo(80f, 45f); lineTo(105f, 48f); lineTo(100f, 65f); lineTo(80f, 60f); close()
            // Right
            moveTo(20f, 45f); lineTo(-5f, 48f); lineTo(0f, 65f); lineTo(20f, 60f); close()
        }

        // 4. Pectorals
        map[MuscleGroup.PECTORALS] = Path().apply {
            // Left
            moveTo(50f, 40f); lineTo(50f, 65f); lineTo(80f, 60f); lineTo(80f, 45f); close()
            // Right
            moveTo(50f, 40f); lineTo(50f, 65f); lineTo(20f, 60f); lineTo(20f, 45f); close()
        }

        // 5. Serratus Anterior (Ribs/Side under armpit)
        map[MuscleGroup.SERRATUS_ANTERIOR] = Path().apply {
            // Left
            moveTo(80f, 60f); lineTo(85f, 80f); lineTo(70f, 70f); close()
            // Right
            moveTo(20f, 60f); lineTo(15f, 80f); lineTo(30f, 70f); close()
        }

        // 6. Abdominals
        map[MuscleGroup.ABDOMINALS] = Path().apply {
            moveTo(40f, 65f); lineTo(60f, 65f); lineTo(58f, 100f); lineTo(42f, 100f); close()
        }

        // 7. Obliques
        map[MuscleGroup.OBLIQUES] = Path().apply {
            // Left
            moveTo(60f, 65f); lineTo(70f, 70f); lineTo(65f, 95f); lineTo(58f, 100f); close()
            // Right
            moveTo(40f, 65f); lineTo(30f, 70f); lineTo(35f, 95f); lineTo(42f, 100f); close()
        }

        // 8. Biceps
        map[MuscleGroup.BICEPS] = Path().apply {
            // Left
            moveTo(100f, 65f); lineTo(105f, 65f); lineTo(108f, 85f); lineTo(98f, 85f); close()
            // Right
            moveTo(0f, 65f); lineTo(-5f, 65f); lineTo(-8f, 85f); lineTo(2f, 85f); close()
        }

        // 9. Forearms
        map[MuscleGroup.FOREARMS] = Path().apply {
            // Left
            moveTo(98f, 85f); lineTo(108f, 85f); lineTo(112f, 110f); lineTo(100f, 110f); close()
            // Right
            moveTo(2f, 85f); lineTo(-8f, 85f); lineTo(-12f, 110f); lineTo(0f, 110f); close()
        }

        // 10. Adductors (Inner Thigh) - Fills gap between quads
        map[MuscleGroup.ADDUCTORS] = Path().apply {
            // Left Inner
            moveTo(50f, 100f); lineTo(60f, 100f); lineTo(56f, 140f); lineTo(52f, 150f); close()
            // Right Inner
            moveTo(50f, 100f); lineTo(40f, 100f); lineTo(44f, 140f); lineTo(48f, 150f); close()
        }

        // 11. Quadriceps (Outer Thighs)
        map[MuscleGroup.QUADRICEPS] = Path().apply {
            // Left
            moveTo(60f, 100f); lineTo(80f, 100f); lineTo(70f, 160f); lineTo(56f, 140f); close()
            // Right
            moveTo(40f, 100f); lineTo(20f, 100f); lineTo(30f, 160f); lineTo(44f, 140f); close()
        }

        // 12. Tibialis (Shins)
        map[MuscleGroup.TIBIALIS] = Path().apply {
            // Left
            moveTo(54f, 165f); lineTo(70f, 165f); lineTo(65f, 210f); lineTo(56f, 210f); close()
            // Right
            moveTo(46f, 165f); lineTo(30f, 165f); lineTo(35f, 210f); lineTo(44f, 210f); close()
        }


        // ===========================================
        // BACK BODY (Offset X = 130 to separate views)
        // ===========================================
        val ox = 130f

        // 13. Trapezius (Upper Back "Diamond")
        map[MuscleGroup.TRAPEZIUS] = Path().apply {
            moveTo(ox + 50f, 35f) // Neck
            lineTo(ox + 85f, 45f); lineTo(ox + 50f, 80f) // Mid back point
            lineTo(ox + 15f, 45f); close()
        }

        // 14. Posterior Deltoids (Rear Delt)
        map[MuscleGroup.POSTERIOR_DELTOIDS] = Path().apply {
            // Left (on right image)
            moveTo(ox + 15f, 45f); lineTo(ox + 0f, 48f); lineTo(ox + 5f, 65f); lineTo(ox + 18f, 65f); close()
            // Right
            moveTo(ox + 85f, 45f); lineTo(ox + 100f, 48f); lineTo(ox + 95f, 65f); lineTo(ox + 82f, 65f); close()
        }

        // 15. Triceps
        map[MuscleGroup.TRICEPS] = Path().apply {
            // Left
            moveTo(ox + 5f, 65f); lineTo(ox + 18f, 65f); lineTo(ox + 15f, 85f); lineTo(ox + 8f, 85f); close()
            // Right
            moveTo(ox + 95f, 65f); lineTo(ox + 82f, 65f); lineTo(ox + 85f, 85f); lineTo(ox + 92f, 85f); close()
        }

        // 16. Latissimus Dorsi (Lats)
        map[MuscleGroup.LATISSIMUS] = Path().apply {
            moveTo(ox + 50f, 80f)
            lineTo(ox + 80f, 65f); lineTo(ox + 75f, 100f)
            lineTo(ox + 50f, 110f)
            lineTo(ox + 25f, 100f); lineTo(ox + 20f, 65f); close()
        }

        // 17. Erectors (Christmas Tree / Lower Back)
        map[MuscleGroup.ERECTORS] = Path().apply {
            moveTo(ox + 50f, 110f); lineTo(ox + 65f, 105f); lineTo(ox + 60f, 120f)
            lineTo(ox + 40f, 120f); lineTo(ox + 35f, 105f); close()
        }

        // 18. Glutes (Buttocks)
        map[MuscleGroup.GLUTES] = Path().apply {
            moveTo(ox + 50f, 120f)
            lineTo(ox + 75f, 120f); lineTo(ox + 75f, 145f); lineTo(ox + 50f, 145f)
            lineTo(ox + 25f, 145f); lineTo(ox + 25f, 120f); close()
        }

        // 19. Abductors (Outer Hip / Glute Medius)
        map[MuscleGroup.ABDUCTORS] = Path().apply {
            // Left (Outer Left)
            moveTo(ox + 25f, 120f); lineTo(ox + 15f, 120f); lineTo(ox + 18f, 140f); lineTo(ox + 25f, 145f); close()
            // Right (Outer Right)
            moveTo(ox + 75f, 120f); lineTo(ox + 85f, 120f); lineTo(ox + 82f, 140f); lineTo(ox + 75f, 145f); close()
        }

        // 20. Hamstrings
        map[MuscleGroup.HAMSTRINGS] = Path().apply {
            // Left Leg
            moveTo(ox + 48f, 145f); lineTo(ox + 25f, 145f); lineTo(ox + 32f, 200f); lineTo(ox + 46f, 200f); close()
            // Right Leg
            moveTo(ox + 52f, 145f); lineTo(ox + 75f, 145f); lineTo(ox + 68f, 200f); lineTo(ox + 54f, 200f); close()
        }

        // 21. Calves (Gastrocnemius)
        map[MuscleGroup.CALVES] = Path().apply {
            // Left
            moveTo(ox + 46f, 205f); lineTo(ox + 32f, 205f); lineTo(ox + 35f, 250f); lineTo(ox + 48f, 250f); close()
            // Right
            moveTo(ox + 54f, 205f); lineTo(ox + 68f, 205f); lineTo(ox + 65f, 250f); lineTo(ox + 52f, 250f); close()
        }

        return map
    }
}