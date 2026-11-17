package com.gabstra.myworkoutassistant.screens

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.window.Dialog
import kotlinx.coroutines.launch
import com.gabstra.myworkoutassistant.DataLayerListenerService
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.sync.pushProfileIndexToWatches
import com.gabstra.myworkoutassistant.shared.profile.UserProfile
import com.gabstra.myworkoutassistant.workout.findActivity

/**
 * Profile list for a shared install. Switching restarts the app so every screen, service and
 * database handle resolves against the newly selected profile.
 */
@Composable
fun UserProfilesCard(
    modifier: Modifier = Modifier,
    onHealthConnectOwnerChanged: () -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var profiles by remember { mutableStateOf(Profiles.profiles(context)) }
    var activeProfileId by remember { mutableStateOf(Profiles.activeProfileId(context)) }
    var healthConnectProfileId by remember { mutableStateOf(Profiles.healthConnectProfileId(context)) }
    var renaming by remember { mutableStateOf<UserProfile?>(null) }
    var deleting by remember { mutableStateOf<UserProfile?>(null) }
    var creating by remember { mutableStateOf(false) }
    var choosingHealthConnect by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf<String?>(null) }

    fun reload() {
        profiles = Profiles.profiles(context)
        activeProfileId = Profiles.activeProfileId(context)
        healthConnectProfileId = Profiles.healthConnectProfileId(context)
        // Watches show this list, so publish it whenever it changes rather than waiting for the
        // next store save.
        scope.launch { pushProfileIndexToWatches(context) }
    }

    StyledCard(modifier = modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(Spacing.md)) {
            profiles.forEach { profile ->
                ProfileRow(
                    profile = profile,
                    isActive = profile.id == activeProfileId,
                    onSelect = {
                        when {
                            profile.id == activeProfileId -> Unit
                            isWorkoutInProgress(context) ->
                                notice = context.getString(
                                    R.string.profile_switch_blocked_workout_in_progress
                                )
                            Profiles.setActiveProfile(context, profile.id) -> restartIntoActiveProfile(context)
                        }
                    },
                    onRename = { renaming = profile },
                    onDelete = { deleting = profile },
                )
                if (profile != profiles.last()) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                }
            }

            ContentSubtitle(
                text = stringResource(R.string.profile_description),
                modifier = Modifier.padding(top = Spacing.sm)
            )

            ContentSubtitle(
                text = stringResource(R.string.profile_health_connect_note),
                modifier = Modifier.padding(top = Spacing.sm)
            )

            AppPrimaryOutlinedButton(
                text = stringResource(
                    R.string.profile_health_connect_button,
                    profiles.firstOrNull { it.id == healthConnectProfileId }?.name
                        ?: stringResource(R.string.profile_health_connect_none)
                ),
                onClick = { choosingHealthConnect = true },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = Spacing.xs)
            )

            AppPrimaryOutlinedButton(
                text = stringResource(R.string.profile_add),
                onClick = { creating = true },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = Spacing.sm)
            )
        }
    }

    notice?.let { message ->
        MessageDialog(
            title = stringResource(R.string.profile_not_switched_title),
            message = message,
            onDismiss = { notice = null },
        )
    }

    if (creating) {
        ProfileNameDialog(
            title = stringResource(R.string.profile_new_title),
            initialName = "",
            confirmLabel = stringResource(R.string.profile_create),
            onDismiss = { creating = false },
            onConfirm = { name ->
                Profiles.create(context, name)
                creating = false
                reload()
            },
        )
    }

    renaming?.let { profile ->
        ProfileNameDialog(
            title = stringResource(R.string.profile_rename_title),
            initialName = profile.name,
            confirmLabel = stringResource(R.string.common_save),
            onDismiss = { renaming = null },
            onConfirm = { name ->
                Profiles.rename(context, profile.id, name)
                renaming = null
                reload()
            },
        )
    }

    if (choosingHealthConnect) {
        ProfileChoiceDialog(
            title = stringResource(R.string.profile_health_connect_title),
            profiles = profiles,
            selectedId = healthConnectProfileId,
            onDismiss = { choosingHealthConnect = false },
            onChoose = { profileId ->
                Profiles.setHealthConnectProfile(context, profileId)
                choosingHealthConnect = false
                reload()
                onHealthConnectOwnerChanged()
            },
        )
    }

    deleting?.let { profile ->
        MessageDialog(
            title = stringResource(R.string.profile_delete_title, profile.name),
            message = stringResource(R.string.profile_delete_message),
            confirmLabel = stringResource(R.string.profile_delete),
            onDismiss = { deleting = null },
            onConfirm = {
                deleting = null
                Profiles.delete(context, profile.id)
                reload()
            },
        )
    }
}

@Composable
private fun ProfileRow(
    profile: UserProfile,
    isActive: Boolean,
    onSelect: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onSelect)
            .padding(vertical = Spacing.xs),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
    ) {
        if (isActive) {
            Icon(
                imageVector = Icons.Filled.Check,
                contentDescription = stringResource(R.string.profile_current_cd),
                tint = MaterialTheme.colorScheme.primary
            )
        }
        Text(
            text = profile.name,
            style = MaterialTheme.typography.bodyLarge,
            color = if (isActive) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f)
        )
        IconButton(onClick = onRename) {
            Icon(
                imageVector = Icons.Filled.Edit,
                contentDescription = stringResource(R.string.profile_rename_cd, profile.name)
            )
        }
        if (!isActive) {
            IconButton(onClick = onDelete) {
                Icon(
                    imageVector = Icons.Filled.Delete,
                    contentDescription = stringResource(R.string.profile_delete_cd, profile.name)
                )
            }
        }
    }
}

@Composable
private fun ProfileChoiceDialog(
    title: String,
    profiles: List<UserProfile>,
    selectedId: String,
    onDismiss: () -> Unit,
    onChoose: (String) -> Unit,
) {
    Dialog(onDismissRequest = onDismiss) {
        StyledCard {
            Column(modifier = Modifier.padding(Spacing.lg)) {
                Text(text = title, style = MaterialTheme.typography.titleMedium)
                profiles.forEach { profile ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onChoose(profile.id) }
                            .padding(vertical = Spacing.sm),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        if (profile.id == selectedId) {
                            Icon(
                                imageVector = Icons.Filled.Check,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                        Text(
                            text = profile.name,
                            style = MaterialTheme.typography.bodyLarge,
                            color = if (profile.id == selectedId) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            },
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
                AppPrimaryOutlinedButton(
                    text = stringResource(R.string.common_cancel),
                    onClick = onDismiss,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
    }
}

@Composable
private fun ProfileNameDialog(
    title: String,
    initialName: String,
    confirmLabel: String,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var name by remember { mutableStateOf(initialName) }
    Dialog(onDismissRequest = onDismiss) {
        StyledCard {
            Column(modifier = Modifier.padding(Spacing.lg)) {
                Text(text = title, style = MaterialTheme.typography.titleMedium)
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    singleLine = true,
                    label = { Text(stringResource(R.string.profile_name_label)) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = Spacing.md)
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    AppPrimaryOutlinedButton(
                        text = stringResource(R.string.common_cancel),
                        onClick = onDismiss,
                        modifier = Modifier.weight(1f)
                    )
                    AppPrimaryOutlinedButton(
                        text = confirmLabel,
                        onClick = { onConfirm(name) },
                        enabled = name.isNotBlank(),
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }
    }
}

@Composable
private fun MessageDialog(
    title: String,
    message: String,
    onDismiss: () -> Unit,
    confirmLabel: String? = null,
    onConfirm: (() -> Unit)? = null,
) {
    Dialog(onDismissRequest = onDismiss) {
        StyledCard {
            Column(modifier = Modifier.padding(Spacing.lg)) {
                Text(text = title, style = MaterialTheme.typography.titleMedium)
                ContentSubtitle(
                    text = message,
                    modifier = Modifier.padding(vertical = Spacing.md)
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                ) {
                    AppPrimaryOutlinedButton(
                        text = if (onConfirm == null) {
                            stringResource(R.string.common_ok)
                        } else {
                            stringResource(R.string.common_cancel)
                        },
                        onClick = onDismiss,
                        modifier = Modifier.weight(1f)
                    )
                    if (onConfirm != null && confirmLabel != null) {
                        AppPrimaryOutlinedButton(
                            text = confirmLabel,
                            onClick = onConfirm,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }
            }
        }
    }
}

private fun isWorkoutInProgress(context: Context): Boolean =
    context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
        .getBoolean("isWorkoutInProgress", false)

private fun restartIntoActiveProfile(context: Context) {
    // Everything cached belongs to the previous profile, so the app restarts — but it comes
    // back to Settings, not the home screen, since that is where the switch was made.
    val intent = Intent(context, MainActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        .putExtra(DataLayerListenerService.PAGE, "settings")
    context.findActivity()?.finish()
    context.startActivity(intent)
}
