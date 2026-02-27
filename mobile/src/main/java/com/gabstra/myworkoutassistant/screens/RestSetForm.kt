package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.CustomTimePicker
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.TimeConverter
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.verticalColumnScrollbarContainer
import java.util.UUID


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RestSetForm(
    onRestSetUpsert: (RestSet) -> Unit,
    onCancel: () -> Unit,
    restSet: RestSet? = null,
    isSaving: Boolean = false
) {
    val hms = remember { mutableStateOf(TimeConverter.secondsToHms(restSet?.timeInSeconds ?: 0)) }
    val (hours, minutes, seconds) = hms.value

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
                        color = MaterialTheme.colorScheme.onBackground,
                        text = if (restSet == null) "Insert Rest" else "Edit Rest",
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
                .padding(vertical = Spacing.sm)
                .verticalColumnScrollbarContainer(scrollState),
        ) {
            Column(modifier = Modifier.fillMaxWidth().padding(Spacing.md)) {
                Text(
                    text = "Rest between sets",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    textAlign = TextAlign.Start
                )
                Spacer(modifier = Modifier.height(Spacing.sm))
                CustomTimePicker(
                    initialHour = hours,
                    initialMinute = minutes,
                    initialSecond = seconds,
                    onTimeChange = { hour, minute, second ->
                        hms.value = Triple(hour, minute, second)
                    }
                )
            }

            Spacer(Modifier.height(Spacing.xl))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacing.md),
                verticalAlignment = Alignment.CenterVertically
            ) {
                AppSecondaryButton(
                    text = "Cancel",
                    onClick = {
                        onCancel()
                    },
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    text = "Save",
                    onClick = {
                        val newRest = RestSet(
                            id = restSet?.id ?: UUID.randomUUID(),
                            timeInSeconds = TimeConverter.hmsToTotalSeconds(hours, minutes, seconds),
                        )

                        onRestSetUpsert(newRest)
                    },
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
    LoadingOverlay(isVisible = rememberDebouncedSavingVisible(isSaving), text = "Saving...")
    }
}



