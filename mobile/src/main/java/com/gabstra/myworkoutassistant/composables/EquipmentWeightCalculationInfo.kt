package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import com.gabstra.myworkoutassistant.ui.theme.tertiaryContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
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

    val lines = getCalculationLines(equipment, totalWeight)

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
                text = stringResource(R.string.loc_how_total_calculated),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurface
            )
            lines.forEach { line ->
                Text(
                    text = line,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiaryContent
                )
            }
        }
    }
}

@Composable
private fun getCalculationLines(
    equipment: WeightLoadedEquipment,
    totalWeight: Double
): List<String> {
    return when (equipment) {
        is Barbell -> {
            val plateTotal = (totalWeight - equipment.barWeight).coerceAtLeast(0.0)
            val platePerSide = plateTotal / 2
            listOf(
                stringResource(R.string.loc_formula_barbell),
                stringResource(R.string.loc_bar_value, formatWeight(equipment.barWeight)),
                stringResource(R.string.loc_plates_per_side_value, formatWeight(platePerSide)),
                stringResource(R.string.loc_plates_total_value, formatWeight(plateTotal)),
            )
        }
        is Dumbbells -> {
            val each = totalWeight / 2
            listOf(
                stringResource(R.string.loc_formula_dumbbells),
                stringResource(R.string.loc_one_dumbbell_value, formatWeight(each)),
            )
        }
        is PlateLoadedCable -> listOf(
            stringResource(R.string.loc_formula_selected_plate_load),
            stringResource(R.string.loc_selected_load_value, formatWeight(totalWeight)),
        )
        is WeightVest -> listOf(
            stringResource(R.string.loc_formula_selected_vest_load),
            stringResource(R.string.loc_selected_load_value, formatWeight(totalWeight)),
        )
        is Machine -> {
            val includesAddOns = equipment.extraWeights.isNotEmpty()
            listOf(
                if (includesAddOns) {
                    stringResource(R.string.loc_formula_machine_addons)
                } else {
                    stringResource(R.string.loc_formula_machine)
                },
                stringResource(R.string.loc_selected_load_value, formatWeight(totalWeight)),
            )
        }
        is Dumbbell -> {
            val includesAddOns = equipment.extraWeights.isNotEmpty()
            listOf(
                if (includesAddOns) {
                    stringResource(R.string.loc_formula_dumbbell_addons)
                } else {
                    stringResource(R.string.loc_formula_dumbbell)
                },
                stringResource(R.string.loc_selected_load_value, formatWeight(totalWeight)),
            )
        }
        else -> listOf(stringResource(R.string.loc_selected_load_value, formatWeight(totalWeight)))
    }
}
