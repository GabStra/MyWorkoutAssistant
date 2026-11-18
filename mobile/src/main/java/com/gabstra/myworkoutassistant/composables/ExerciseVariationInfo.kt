package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.ExerciseType

@Composable
fun ExerciseVariationInfo(
    exerciseType: ExerciseType,
    targetRepRange: String?,
    equipmentName: String?,
    accessoryNames: List<String>,
    modifier: Modifier = Modifier,
    definitionName: String? = null,
    displayName: String? = null,
) {
    val equipment = equipmentName?.takeIf { it.isNotBlank() } ?: stringResource(R.string.common_none)
    val accessories = accessoryNames.filter { it.isNotBlank() }.distinct()
    val libraryName = definitionName
        ?.takeIf { it.isNotBlank() && it != displayName }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        VariationDetailRow(label = stringResource(R.string.loc_type)) {
            VariationDetailValue(exerciseType.variationTypeLabel())
        }
        if (exerciseType == ExerciseType.WEIGHT || exerciseType == ExerciseType.BODY_WEIGHT) {
            VariationDetailRow(label = stringResource(R.string.loc_target_reps)) {
                VariationDetailValue(
                    targetRepRange?.takeIf { it.isNotBlank() } ?: stringResource(R.string.common_not_set)
                )
            }
        }
        VariationDetailRow(label = stringResource(R.string.exercise_equipment)) {
            VariationDetailValue(equipment)
        }
        if (accessories.isNotEmpty()) {
            VariationDetailRow(label = stringResource(R.string.exercise_accessories)) {
                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    accessories.forEach { accessory ->
                        VariationDetailValue(accessory)
                    }
                }
            }
        }
        libraryName?.let { name ->
            VariationDetailRow(label = stringResource(R.string.loc_library_exercise)) {
                VariationDetailValue(name)
            }
        }
    }
}

@Composable
private fun VariationDetailRow(
    label: String,
    content: @Composable () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            text = label,
            modifier = Modifier.width(112.dp),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Column(modifier = Modifier.weight(1f)) {
            content()
        }
    }
}

@Composable
private fun VariationDetailValue(value: String) {
    Text(
        text = value,
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurface,
    )
}

@Composable
private fun ExerciseType.variationTypeLabel(): String = stringResource(
    when (this) {
        ExerciseType.WEIGHT -> R.string.loc_exercise_type_weight
        ExerciseType.BODY_WEIGHT -> R.string.loc_exercise_type_body_weight
        ExerciseType.COUNTUP -> R.string.loc_exercise_type_count_up
        ExerciseType.COUNTDOWN -> R.string.loc_exercise_type_count_down
        ExerciseType.RUNNING -> R.string.history_running_fallback
    }
)
