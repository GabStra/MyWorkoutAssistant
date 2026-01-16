package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise

@Composable
fun ExerciseRenderer(
    exercise: Exercise,
    modifier: Modifier = Modifier,
    showRest:Boolean,
    appViewModel: AppViewModel,
    customTitle: (@Composable (Modifier) -> Unit)? = null
){
    var sets = exercise.sets

    if(!showRest)
        sets = sets.filter { it !is RestSet }

    if(sets.isEmpty()){
        Row(
            modifier = Modifier.padding(15.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically
        ){
            Text(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 10.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE),
                text = exercise.name,
                style = MaterialTheme.typography.bodyLarge,
                color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
            )
        }
    }else{
        ExpandableContainer(
            isOpen = false,
            modifier = modifier,
            isExpandable = true,
            title = { m ->
                if (customTitle != null) {
                    customTitle(m)
                } else {
                    Text(
                        modifier = m
                            .fillMaxWidth()
                            .padding(horizontal = 10.dp)
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        text = exercise.name,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (exercise.enabled) MaterialTheme.colorScheme.onBackground else DisabledContentGray,
                    )
                }
            },
            content = {
                Column(
                    modifier = Modifier.padding(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    val equipment = if(exercise.equipmentId != null) appViewModel.getEquipmentById(exercise.equipmentId!!) else null
                    val accessoryEquipments = (exercise.requiredAccessoryEquipmentIds ?: emptyList()).mapNotNull { id ->
                        appViewModel.getAccessoryEquipmentById(id)
                    }
                    val textColor = if (exercise.enabled) {
                        MaterialTheme.colorScheme.onBackground
                    } else {
                        DisabledContentGray
                    }
                    val headerStyle = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold)
                    val headerColor = MaterialTheme.colorScheme.onSurface
                    val rowPadding = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)

                    if(equipment != null){
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            textAlign = TextAlign.Center,
                            text = "Equipment: ${equipment.name}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = textColor
                        )
                    }
                    if(accessoryEquipments.isNotEmpty()){
                        val accessoryNames = accessoryEquipments.joinToString(", ") { it.name }
                        Text(
                            modifier = Modifier.fillMaxWidth(),
                            textAlign = TextAlign.Center,
                            text = "Accessory: $accessoryNames",
                            style = MaterialTheme.typography.bodyMedium,
                            color = textColor
                        )
                    }

                    var index = 0
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        color = MaterialTheme.colorScheme.surface
                    ) {
                        Column {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(MaterialTheme.colorScheme.surfaceVariant)
                                    .padding(vertical = 6.dp, horizontal = 12.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(
                                    modifier = Modifier.weight(1f),
                                    text = "SET",
                                    style = headerStyle,
                                    textAlign = TextAlign.Center,
                                    color = headerColor,
                                )
                                if(exercise.exerciseType == ExerciseType.BODY_WEIGHT || exercise.exerciseType == ExerciseType.WEIGHT){
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "WEIGHT (KG)",
                                        style = headerStyle,
                                        textAlign = TextAlign.Center,
                                        color = headerColor,
                                    )
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "REPS",
                                        style = headerStyle,
                                        textAlign = TextAlign.Center,
                                        color = headerColor,
                                    )
                                }else{
                                    Text(
                                        modifier = Modifier.weight(2f),
                                        text = "TIME",
                                        textAlign = TextAlign.Center,
                                        style = headerStyle,
                                        color = headerColor,
                                    )
                                }
                            }

                            sets.forEachIndexed { setIndex, set ->
                                if(set !is RestSet){
                                    index += 1
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .then(rowPadding),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            modifier = Modifier.weight(1f),
                                            text = "$index",
                                            style = MaterialTheme.typography.bodyMedium,
                                            textAlign = TextAlign.Center,
                                            color = textColor,
                                        )
                                        when (set) {
                                            is WeightSet -> {
                                                val isCalibrationEnabled = exercise.requiresLoadCalibration
                                                
                                                val weightText = if (isCalibrationEnabled) {
                                                    "Calibration"
                                                } else {
                                                    equipment!!.formatWeight(set.weight)
                                                }
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = weightText,
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = "${set.reps}",
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                            }

                                            is BodyWeightSet -> {
                                                val isCalibrationEnabled = exercise.requiresLoadCalibration && equipment != null
                                                
                                                val weightText = when {
                                                    isCalibrationEnabled && set.additionalWeight > 0 -> "Cal"
                                                    isCalibrationEnabled -> "-"
                                                    set.additionalWeight > 0 -> equipment!!.formatWeight(set.additionalWeight)
                                                    else -> "-"
                                                }
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = weightText,
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                                Text(
                                                    modifier = Modifier.weight(1f),
                                                    text = "${set.reps}",
                                                    textAlign = TextAlign.Center,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                    color = textColor,
                                                )
                                            }

                                            is TimedDurationSet -> {
                                                Text(
                                                    modifier = Modifier.weight(2f),
                                                    text = formatTime(set.timeInMillis / 1000),
                                                    style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                                                    textAlign = TextAlign.Center,
                                                    color = textColor,
                                                )
                                            }

                                            is EnduranceSet -> {
                                                Text(
                                                    modifier = Modifier.weight(2f),
                                                    text =formatTime(set.timeInMillis / 1000),
                                                    style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                                                    textAlign = TextAlign.Center,
                                                    color = textColor,
                                                )
                                            }
                                            else -> throw IllegalArgumentException("Unknown set type")
                                        }
                                    }
                                }else{
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .then(rowPadding),
                                        horizontalArrangement = Arrangement.Center,
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        Text(
                                            "REST ${formatTime(set.timeInSeconds)}",
                                            style = MaterialTheme.typography.bodyMedium,
                                            color = textColor,
                                        )
                                    }
                                }

                                if (setIndex < sets.size - 1) {
                                    HorizontalDivider(
                                        color = MaterialTheme.colorScheme.outlineVariant,
                                        modifier = Modifier.padding(horizontal = 12.dp)
                                    )
                                }
                            }
                        }
                    }
                }
            }
        )
    }
}

