package com.gabstra.myworkoutassistant.screens.equipments

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold
import com.gabstra.myworkoutassistant.shared.equipments.CardioMachine
import java.util.UUID

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CardioMachineForm(
    onUpsert: (CardioMachine) -> Unit,
    onCancel: () -> Unit,
    cardioMachine: CardioMachine? = null,
) {
    val nameState = rememberSaveable { mutableStateOf(cardioMachine?.name.orEmpty()) }
    val scrollState = rememberScrollState()

    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
                title = {
                    Text(
                        text = if (cardioMachine == null) "Create Cardio Machine" else "Edit Cardio Machine",
                        modifier = Modifier.fillMaxWidth().basicMarquee(iterations = Int.MAX_VALUE),
                        color = MaterialTheme.colorScheme.onBackground,
                        textAlign = TextAlign.Center,
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    IconButton(modifier = Modifier.alpha(0f), onClick = onCancel) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = null)
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(vertical = Spacing.sm)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.md),
            verticalArrangement = Arrangement.spacedBy(Spacing.sm),
        ) {
            EquipmentFormSection(title = "Details") {
                OutlinedTextField(
                    value = nameState.value,
                    onValueChange = { nameState.value = it },
                    label = { Text("Name", style = MaterialTheme.typography.labelLarge) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            EquipmentFormActions(
                saveEnabled = nameState.value.isNotBlank(),
                onCancel = onCancel,
                onSave = {
                    onUpsert(
                        CardioMachine(
                            id = cardioMachine?.id ?: UUID.randomUUID(),
                            name = nameState.value.trim(),
                        )
                    )
                },
            )
        }
    }
}
