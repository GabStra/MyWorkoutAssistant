package com.gabstra.myworkoutassistant.screens

import android.widget.Toast
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.BodyWeightSetForm
import com.gabstra.myworkoutassistant.composables.CustomButton
import com.gabstra.myworkoutassistant.composables.EnduranceSetForm
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.TimedDurationSetForm
import com.gabstra.myworkoutassistant.composables.WeightSetForm
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetType
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.verticalColumnScrollbar


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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SetForm(
    viewModel: AppViewModel,
    onSetUpsert: (Set) -> Unit,
    onCancel: () -> Unit,
    set: Set? = null, // Add exercise parameter with default value null
    exerciseType : ExerciseType,
    exercise: Exercise,
    isSaving: Boolean = false
) {
    val selectedSetType = remember { mutableStateOf(getSetTypeFromExerciseType(exerciseType)) }
    val equipment = exercise.equipmentId?.let { viewModel.getEquipmentById(it) }

    val outlineVariant = MaterialTheme.colorScheme.outlineVariant
    Box(modifier = Modifier.fillMaxSize()) {
        Scaffold(
        topBar = {
            TopAppBar(
                modifier = Modifier.drawBehind {
                        drawLine(
                            color = outlineVariant,
                            start = Offset(0f, size.height),
                            end = Offset(size.width, size.height),
                            strokeWidth = 1.dp.toPx()
                        )
                    },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color.Transparent,
                    navigationIconContentColor = MaterialTheme.colorScheme.onBackground,
                    actionIconContentColor = MaterialTheme.colorScheme.onBackground
                ),
                title = {
                    Text(
                        modifier = Modifier
                            .fillMaxWidth()
                            .basicMarquee(iterations = Int.MAX_VALUE),
                        color = MaterialTheme.colorScheme.onBackground,
                        textAlign = TextAlign.Center,
                        text = if(set == null) "Insert Set" else "Edit Set",
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel, enabled = !isSaving) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                },
                actions = {
                    IconButton(modifier = Modifier.alpha(0f), onClick = { onCancel() }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back"
                        )
                    }
                }
            )
        }
    ) { it ->
        val scrollState = rememberScrollState()
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(it)
                .padding(top = 10.dp)
                .padding(bottom = 10.dp)
                .verticalColumnScrollbar(scrollState)
                .verticalScroll(scrollState)
                .padding(horizontal = 15.dp),
        ) {
            if (set == null) {
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
                    if (equipment == null) {
                        val context = LocalContext.current
                        Toast.makeText(
                            context,
                            "Equipment must be assigned to the exercise first",
                            Toast.LENGTH_LONG
                        ).show()
                        onCancel()
                        return@Scaffold
                    }

                    WeightSetForm(
                        onSetUpsert = onSetUpsert,
                        weightSet = set as WeightSet?,
                        equipment = equipment!!
                    )
                }

                SetType.BODY_WEIGHT_SET -> {
                    BodyWeightSetForm(
                        onSetUpsert = onSetUpsert,
                        bodyWeightSet = set as BodyWeightSet?,
                        equipment = equipment
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

            CustomButton(
                text = "Cancel",
                onClick = {
                    onCancel()
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacing.sm)
            )
        }
    }
    LoadingOverlay(isVisible = isSaving, text = "Saving...")
    }
}

