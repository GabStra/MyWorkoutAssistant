package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.composables.BodyWeightSetForm
import com.gabstra.myworkoutassistant.composables.EnduranceSetForm
import com.gabstra.myworkoutassistant.composables.TimedDurationSetForm
import com.gabstra.myworkoutassistant.composables.WeightSetForm
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetType
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import java.util.UUID


fun SetType.toReadableString(): String {
    return this.name.replace('_', ' ').split(' ').joinToString(" ") { it.capitalize() }
}

fun getSetTypeFromExerciseType(exerciseType: ExerciseType): SetType {
    return when (exerciseType) {
        ExerciseType.WEIGHT -> SetType.WEIGHT_SET
        ExerciseType.BODY_WEIGHT -> SetType.BODY_WEIGHT_SET
        ExerciseType.COUNTUP -> SetType.COUNTUP_SET
        ExerciseType.COUNTDOWN -> SetType.COUNTDOWN_SET
    }
}

@Composable
fun SetForm(
    viewModel: AppViewModel,
    onSetUpsert: (Set) -> Unit,
    onCancel: () -> Unit,
    set: Set? = null, // Add exercise parameter with default value null
    exerciseType : ExerciseType,
) {
    val selectedSetType = remember { mutableStateOf(getSetTypeFromExerciseType(exerciseType)) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.Center,
    ){
        if(set == null){
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            ) {
                Text(text = "Set Type:")
                Box(modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = selectedSetType.value.name.replace('_', ' ').capitalize(),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp)
                    )
                }
            }
            Spacer(modifier = Modifier.height(10.dp))
        }

        when (selectedSetType.value) {
            SetType.WEIGHT_SET -> {
                WeightSetForm(
                    onSetUpsert = onSetUpsert,
                    weightSet = set as WeightSet?,
                )
            }
            SetType.BODY_WEIGHT_SET -> {
                BodyWeightSetForm(
                    onSetUpsert = onSetUpsert,
                    bodyWeightSet = set as BodyWeightSet?
                )
            }
            SetType.COUNTUP_SET -> {
                EnduranceSetForm(
                    onSetUpsert = onSetUpsert,
                    enduranceSet = set as EnduranceSet?,
                )
            }
            SetType.COUNTDOWN_SET -> {
                TimedDurationSetForm(
                    onSetUpsert = onSetUpsert,
                    timedDurationSet = set as TimedDurationSet?,
                )
            }
        }

        Button(
            colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
            onClick = {
                onCancel()
            },
            modifier = Modifier
                .fillMaxWidth()
                .padding(8.dp)
        ) {
            Text("Cancel")
        }
    }
}