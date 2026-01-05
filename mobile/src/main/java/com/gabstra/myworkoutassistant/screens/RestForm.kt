package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.composables.CustomButton
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.SavingOverlay
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.Spacing

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RestForm(
    onRestUpsert: (Rest) -> Unit,
    onCancel: () -> Unit,
    rest: Rest? = null, // Add exercise parameter with default value null
    isSaving: Boolean = false,
    workout: Workout? = null
) {
    val hms = remember { mutableStateOf(TimeConverter.secondsToHms(rest?.timeInSeconds ?: 0)) }
    val (hours, minutes, seconds) = hms.value

    val titleText = if (rest == null) {
        "Insert Rest"
    } else {
        val allRests = workout?.workoutComponents?.filterIsInstance<Rest>() ?: emptyList()
        val restCount = allRests.size
        if (restCount > 1) {
            val restIndex = allRests.indexOf(rest)
            if (restIndex >= 0) {
                "Edit Rest (${restIndex + 1} of $restCount)"
            } else {
                "Edit Rest"
            }
        } else {
            "Edit Rest"
        }
    }

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
                        textAlign = TextAlign.Center,
                        text = titleText,
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

            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
            ) {
                Text("Rest between exercises")
                Spacer(modifier = Modifier.height(15.dp))
                CustomTimePicker(
                    initialHour = hours,
                    initialMinute = minutes,
                    initialSecond = seconds,
                    onTimeChange = { hour, minute, second ->
                        hms.value = Triple(hour, minute, second)
                    }
                )
            }

            // Submit button
            Button(
                colors = ButtonDefaults.buttonColors(
                    contentColor = MaterialTheme.colorScheme.background,
                    disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant
                ),
                onClick = {
                    val newRest = Rest(
                        id = rest?.id ?: java.util.UUID.randomUUID(),
                        enabled = rest?.enabled ?: true,
                        timeInSeconds = TimeConverter.hmsToTotalSeconds(hours, minutes, seconds),
                    )

                    onRestUpsert(newRest)
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp),
            ) {
                if (rest == null) Text("Insert Rest") else Text("Edit Rest")
            }

            Spacer(modifier = Modifier.height(Spacing.md))

            // Cancel button
            CustomButton(
                text = "Cancel",
                onClick = {
                    onCancel()
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(8.dp)
            )
        }
    }
    SavingOverlay(isSaving = isSaving)
    }
}

