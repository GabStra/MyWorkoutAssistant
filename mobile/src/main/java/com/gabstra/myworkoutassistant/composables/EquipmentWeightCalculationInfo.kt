package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.formatWeight

@Composable
fun EquipmentWeightCalculationInfo(
    equipment: WeightLoadedEquipment,
    totalWeight: Double,
    modifier: Modifier = Modifier
) {
    if (totalWeight <= 0.0) return

    val lines = remember(equipment, totalWeight) {
        getCalculationLines(equipment, totalWeight)
    }

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 4.dp),
        tonalElevation = 0.dp,
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.35f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant)
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp)
        ) {
            Text(
                text = "How total is calculated",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurface
            )
            lines.forEach { line ->
                Text(
                    text = line,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

private fun getCalculationLines(
    equipment: WeightLoadedEquipment,
    totalWeight: Double
): List<String> {
    return when (equipment) {
        is Barbell -> {
            val plateTotal = (totalWeight - equipment.barWeight).coerceAtLeast(0.0)
            val platePerSide = plateTotal / 2
            listOf(
                "Formula: total = bar + (plates per side x 2)",
                "Bar: ${formatWeight(equipment.barWeight)} kg",
                "Plates per side: ${formatWeight(platePerSide)} kg",
                "Plates total: ${formatWeight(plateTotal)} kg"
            )
        }
        is Dumbbells -> {
            val each = totalWeight / 2
            listOf(
                "Formula: total = one dumbbell x 2",
                "One dumbbell: ${formatWeight(each)} kg"
            )
        }
        is PlateLoadedCable -> listOf(
            "Formula: total = selected plate load",
            "Selected load: ${formatWeight(totalWeight)} kg"
        )
        is WeightVest -> listOf(
            "Formula: total = selected vest load",
            "Selected load: ${formatWeight(totalWeight)} kg"
        )
        is Machine -> {
            val includesAddOns = equipment.extraWeights.isNotEmpty()
            listOf(
                if (includesAddOns) {
                    "Formula: total = selected stack/load + selected add-on weights"
                } else {
                    "Formula: total = selected stack/load"
                },
                "Selected load: ${formatWeight(totalWeight)} kg"
            )
        }
        is Dumbbell -> {
            val includesAddOns = equipment.extraWeights.isNotEmpty()
            listOf(
                if (includesAddOns) {
                    "Formula: total = selected dumbbell + selected add-on weights"
                } else {
                    "Formula: total = selected dumbbell"
                },
                "Selected load: ${formatWeight(totalWeight)} kg"
            )
        }
        else -> listOf("Selected load: ${formatWeight(totalWeight)} kg")
    }
}
