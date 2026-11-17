package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.shared.Workout
import java.util.UUID

@Composable
fun RecurringSessionDialog(
    family: List<Workout>,
    attachableWorkouts: List<Workout>,
    onRename: (String) -> Unit,
    onUpdatePrescriptionLabel: (Workout, String?) -> Unit,
    onAttach: (Workout) -> Unit,
    onDetach: (Workout) -> Unit,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val activeFamily = family.filter { it.isActive }.sortedBy { it.prescriptionOrdinal }
    val nameState = remember(family) { mutableStateOf(activeFamily.firstOrNull()?.name.orEmpty()) }
    val labels = remember(family) {
        mutableStateMapOf<UUID, String>().apply {
            activeFamily.forEach { put(it.id, it.prescriptionLabel.orEmpty()) }
        }
    }
    var expandedAttach by remember { mutableStateOf(false) }
    var error by remember(family) { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.dialog_manage_recurring_session)) },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 560.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                OutlinedTextField(
                    value = nameState.value,
                    onValueChange = { nameState.value = it; error = null },
                    label = { Text(stringResource(R.string.dialog_session_name)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag("recurring_session_name"),
                )
                Text(
                    text = stringResource(R.string.dialog_recurring_session_explanation),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(
                    modifier = Modifier.fillMaxWidth().testTag("rename_recurring_session"),
                    onClick = {
                        val name = nameState.value.trim()
                        if (name.isEmpty()) {
                            error = context.getString(R.string.dialog_enter_session_name_error)
                        } else {
                            onRename(name)
                            error = null
                        }
                    },
                ) { Text(stringResource(R.string.dialog_rename_session)) }

                activeFamily.forEach { workout ->
                    key(workout.id) {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text(workout.name, style = MaterialTheme.typography.titleSmall)
                        OutlinedTextField(
                            value = labels[workout.id].orEmpty(),
                            onValueChange = { labels[workout.id] = it; error = null },
                            label = { Text(stringResource(R.string.dialog_prescription_label)) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth().testTag("prescription_label_${workout.id}"),
                        )
                        Button(
                            modifier = Modifier.fillMaxWidth().testTag("save_prescription_${workout.id}"),
                            onClick = {
                                onUpdatePrescriptionLabel(workout, labels[workout.id])
                                error = null
                            },
                        ) { Text(stringResource(R.string.dialog_save_label)) }
                        OutlinedButton(
                            modifier = Modifier.fillMaxWidth().testTag("make_standalone_workout_${workout.id}"),
                            onClick = { onDetach(workout) },
                        ) {
                            Text(stringResource(R.string.dialog_make_standalone))
                        }
                        Text(
                            text = stringResource(R.string.dialog_make_standalone_description),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    }
                }

                if (attachableWorkouts.isNotEmpty()) {
                    Column {
                        OutlinedButton(
                            onClick = { expandedAttach = true },
                            modifier = Modifier.fillMaxWidth().testTag("attach_existing_workout"),
                        ) { Text(stringResource(R.string.dialog_add_existing_workout)) }
                        DropdownMenu(expanded = expandedAttach, onDismissRequest = { expandedAttach = false }) {
                            attachableWorkouts.forEach { candidate ->
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            candidate.description.takeIf { it.isNotBlank() }?.let {
                                                "${candidate.name} — $it"
                                            } ?: stringResource(
                                                R.string.dialog_workout_ordinal,
                                                candidate.name,
                                                candidate.order + 1
                                            )
                                        )
                                    },
                                    onClick = { expandedAttach = false; onAttach(candidate) },
                                )
                            }
                        }
                    }
                }
                Text(
                    text = stringResource(R.string.dialog_after_adding_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.dialog_done)) } },
        dismissButton = {
            TextButton(
                modifier = Modifier.testTag("cancel_recurring_session"),
                onClick = onDismiss,
            ) { Text(stringResource(R.string.common_cancel)) }
        },
    )

}
