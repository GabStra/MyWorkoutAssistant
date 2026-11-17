package com.gabstra.myworkoutassistant.screens

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.LocalContentColor
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.composables.ButtonWithText
import com.gabstra.myworkoutassistant.composables.WearTonalContentButton
import com.gabstra.myworkoutassistant.composables.rememberWearCoroutineScope
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.profile.UserProfile
import com.gabstra.myworkoutassistant.sync.publishProfileBinding
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val WORKOUT_STATE_PREFERENCES = "workout_state"
private const val WORKOUT_IN_PROGRESS_KEY = "isWorkoutInProgress"

/**
 * Lets this watch choose the profile it follows. The choice is local, and it is reported to the
 * phone so the phone sends this watch that profile's data instead of whatever it is showing.
 */
@Composable
fun ProfilePickerDialog(
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberWearCoroutineScope()

    val profiles = remember(context) { Profiles.profiles(context) }
    val activeProfileId = remember(context) { Profiles.activeProfileId(context) }
    val workoutInProgress = remember(context) {
        context.getSharedPreferences(WORKOUT_STATE_PREFERENCES, Context.MODE_PRIVATE)
            .getBoolean(WORKOUT_IN_PROGRESS_KEY, false)
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = false,
            usePlatformDefaultWidth = false,
        ),
    ) {
        Box(
            modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp, vertical = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = stringResource(R.string.wear_profiles),
                    style = MaterialTheme.typography.titleMedium,
                    textAlign = TextAlign.Center,
                )

                when {
                    workoutInProgress -> ProfilePickerMessage(stringResource(R.string.wear_profiles_finish_or_discard_first))
                    profiles.size < 2 -> ProfilePickerMessage(stringResource(R.string.wear_profiles_add_in_phone_app))
                    else -> profiles.forEach { profile ->
                        ProfileRow(
                            profile = profile,
                            active = profile.id == activeProfileId,
                            onSelect = {
                                scope.launch {
                                    val switched = withContext(Dispatchers.IO) {
                                        Profiles.setLocallyChosenProfile(context, profile.id)
                                    }
                                    if (switched) {
                                        publishProfileBinding(context, profile.id)
                                        restartAfterProfileChange(context)
                                    }
                                }
                            },
                        )
                    }
                }

                Spacer(modifier = Modifier.height(4.dp))
                ButtonWithText(
                    text = stringResource(R.string.wear_close),
                    onClick = onDismiss,
                )
            }
        }
    }
}

/** Everything already loaded belongs to the previous profile, so start clean. */
private fun restartAfterProfileChange(context: Context) {
    val intent = Intent(context, MainActivity::class.java)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
    context.startActivity(intent)
}

@Composable
private fun ProfilePickerMessage(text: String) {
    Text(
        modifier = Modifier.fillMaxWidth(),
        text = text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
    )
}

@Composable
private fun ProfileRow(
    profile: UserProfile,
    active: Boolean,
    onSelect: () -> Unit,
) {
    WearTonalContentButton(
        modifier = Modifier.fillMaxWidth(),
        enabled = !active,
        onClick = onSelect,
    ) {
        ProfileRowContent(name = profile.name, active = active)
    }
}

@Composable
private fun RowScope.ProfileRowContent(
    name: String,
    active: Boolean,
) {
    Text(
        modifier = Modifier.weight(1f).padding(start = 8.dp),
        text = name,
        style = MaterialTheme.typography.labelMedium,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
    if (active) {
        Icon(
            modifier = Modifier.size(18.dp),
            imageVector = Icons.Default.Check,
            contentDescription = stringResource(R.string.wear_active_profile_cd),
            tint = LocalContentColor.current,
        )
    }
}
