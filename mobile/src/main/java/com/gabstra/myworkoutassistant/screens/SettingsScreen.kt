package com.gabstra.myworkoutassistant.screens

import com.gabstra.myworkoutassistant.composables.BreadcrumbScaffold

import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
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
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Checkbox
import androidx.compose.foundation.clickable
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeightRecord
import androidx.health.connect.client.records.WeightRecord
import com.gabstra.myworkoutassistant.MobileLlmFeatureFlags
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.Spacing
import com.gabstra.myworkoutassistant.composables.AppPrimaryButton
import com.gabstra.myworkoutassistant.composables.AppPrimaryOutlinedButton
import com.gabstra.myworkoutassistant.composables.AppSecondaryButton
import com.gabstra.myworkoutassistant.composables.ContentSubtitle
import com.gabstra.myworkoutassistant.composables.FormSectionTitle
import com.gabstra.myworkoutassistant.composables.LoadingOverlay
import com.gabstra.myworkoutassistant.composables.StyledCard
import com.gabstra.myworkoutassistant.composables.rememberDebouncedSavingVisible
import com.gabstra.myworkoutassistant.getHistoricalRestingHeartRateFromHealthConnect
import com.gabstra.myworkoutassistant.getHistoricalVo2MaxFromHealthConnect
import com.gabstra.myworkoutassistant.getLatestBodyMeasurementsFromHealthConnect
import com.gabstra.myworkoutassistant.insights.LiteRtLmBackendPreference
import com.gabstra.myworkoutassistant.insights.RemoteOpenAiConfig
import com.gabstra.myworkoutassistant.insights.RemoteModelCatalog
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsMode
import com.gabstra.myworkoutassistant.shared.DeloadConfig
import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.PolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.WhoopHeartRateConfig
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.running.DistanceUnit
import com.gabstra.myworkoutassistant.shared.findPolarHeartRateConfig
import com.gabstra.myworkoutassistant.shared.findWhoopHeartRateConfig
import com.gabstra.myworkoutassistant.shared.getEffectiveRestingHeartRate
import com.gabstra.myworkoutassistant.shared.getMaxHeartRate
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.util.Calendar

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onSave: (WorkoutStore) -> Unit,
    onCancel: () -> Unit,
    workoutStore: WorkoutStore,
    healthConnectClient: HealthConnectClient,
    mobileLlmEnabled: Boolean,
    workoutInsightsMode: WorkoutInsightsMode,
    liteRtModelPath: String?,
    liteRtModelName: String?,
    liteRtBackendPreference: LiteRtLmBackendPreference,
    remoteInsightsConfig: RemoteOpenAiConfig,
    workoutInsightsCustomInstructions: String,
    onImportLiteRtModel: () -> Unit,
    onSaveInsightsSettings: (
        Boolean,
        WorkoutInsightsMode,
        LiteRtLmBackendPreference,
        RemoteOpenAiConfig,
        String,
    ) -> Unit,
    onClearLiteRtModel: () -> Unit,
    isSaving: Boolean = false,
    isImportingLiteRtModel: Boolean = false
) {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    // Health Connect belongs to one profile, so another profile must not read its values.
    // The owner can be changed from the profiles card below, hence the revision key.
    var healthConnectRevision by remember { mutableStateOf(0) }
    val canUseHealthConnect = remember(healthConnectRevision) {
        Profiles.isHealthConnectProfile(context)
    }
    val defaultRestingHeartRate = getEffectiveRestingHeartRate()
    val polarConfig = remember(workoutStore.externalHeartRateConfigs) { workoutStore.findPolarHeartRateConfig() }
    val whoopConfig = remember(workoutStore.externalHeartRateConfigs) { workoutStore.findWhoopHeartRateConfig() }

    val polarDeviceIdState = remember { mutableStateOf(polarConfig?.deviceId ?: "") }
    val polarDisplayNameState = remember { mutableStateOf(polarConfig?.displayName ?: "") }
    val whoopDeviceIdState = remember { mutableStateOf(whoopConfig?.deviceId ?: "") }
    val whoopDisplayNameState = remember { mutableStateOf(whoopConfig?.displayName ?: "") }
    val visiblePlanIdsState = remember {
        mutableStateOf(workoutStore.visibleWorkoutPlanIds?.toSet())
    }
    val birthDateYearState = remember { mutableStateOf(workoutStore.birthDateYear.toString()) }
    val weightState = remember { mutableStateOf(workoutStore.weightKg.toString()) }
    val heightState = remember { mutableStateOf(workoutStore.heightCm?.toString() ?: "") }
    val distanceUnitState = remember { mutableStateOf(workoutStore.distanceUnit) }
    val measuredMaxHeartRateState = remember { mutableStateOf(workoutStore.measuredMaxHeartRate?.toString() ?: "") }
    val restingHeartRateState = remember {
        mutableStateOf(getEffectiveRestingHeartRate(workoutStore.restingHeartRate).toString())
    }
    val deloadFailedSessionsThresholdState = remember {
        mutableStateOf(workoutStore.deloadConfig.failedSessionsThreshold?.toString() ?: "")
    }
    val deloadCompletedSessionsIntervalState = remember {
        mutableStateOf(workoutStore.deloadConfig.completedSessionsInterval?.toString() ?: "")
    }
    val deloadWeightFactorState = remember {
        mutableStateOf(workoutStore.deloadConfig.weightFactor.toString())
    }
    val deloadRepsDropState = remember {
        mutableStateOf(workoutStore.deloadConfig.repsDrop.toString())
    }
    val deloadCutSetsToState = remember {
        mutableStateOf(workoutStore.deloadConfig.cutSetsTo?.toString() ?: "")
    }
    val mobileLlmEnabledState = remember { mutableStateOf(mobileLlmEnabled) }
    val workoutInsightsModeState = remember { mutableStateOf(workoutInsightsMode) }
    val liteRtBackendPreferenceState = remember { mutableStateOf(liteRtBackendPreference) }
    val remoteBaseUrlState = remember { mutableStateOf(remoteInsightsConfig.baseUrl) }
    val remoteApiKeyState = remember { mutableStateOf(remoteInsightsConfig.apiKey) }
    val remoteModelState = remember { mutableStateOf(remoteInsightsConfig.model) }
    val workoutInsightsCustomInstructionsState = remember { mutableStateOf(workoutInsightsCustomInstructions) }
    var remoteModels by remember { mutableStateOf<List<String>>(emptyList()) }
    var isFetchingRemoteModels by remember { mutableStateOf(false) }
    var remoteModelsError by remember { mutableStateOf<String?>(null) }
    var remoteModelsMenuExpanded by remember { mutableStateOf(false) }

    // The fetched catalog belongs to one endpoint+credential pair; drop it when either changes.
    LaunchedEffect(remoteBaseUrlState.value, remoteApiKeyState.value) {
        remoteModels = emptyList()
        remoteModelsMenuExpanded = false
    }

    fun loadRemoteModels() {
        if (isFetchingRemoteModels) return
        val baseUrl = remoteBaseUrlState.value.trim()
        if (baseUrl.isBlank()) {
            remoteModelsError = context.getString(R.string.settings_enter_base_url)
            return
        }
        isFetchingRemoteModels = true
        remoteModelsError = null
        coroutineScope.launch {
            RemoteModelCatalog.fetchModelIds(baseUrl, remoteApiKeyState.value)
                .onSuccess { models ->
                    remoteModels = models
                    remoteModelsMenuExpanded = models.isNotEmpty()
                }
                .onFailure { error ->
                    remoteModelsError = error.message ?: context.getString(R.string.settings_model_list_failed)
                }
            isFetchingRemoteModels = false
        }
    }

    var isLoadingRestingHeartRate by remember { mutableStateOf(false) }
    var isLoadingVo2Max by remember { mutableStateOf(false) }
    var isLoadingBodyMeasurements by remember { mutableStateOf(false) }
    // TrackerUserProfile convention: 0 = male, 1 = female, null = unset (watch reads gender by name).
    // Falls back to the legacy sex flag so existing users keep their selection.
    val genderState = remember {
        mutableStateOf(
            workoutStore.gender ?: when (workoutStore.sex) {
                true -> 1
                false -> 0
                null -> null
            }
        )
    }
    val vo2MaxState = remember {
        mutableStateOf(workoutStore.estimatedVo2MaxMlKgMin?.toString() ?: "")
    }
    val currentYear = remember { Calendar.getInstance().get(Calendar.YEAR) }
    val fallbackBirthYear = birthDateYearState.value.toIntOrNull()
    val fallbackAge = fallbackBirthYear?.let { year ->
        (currentYear - year).takeIf { it in 1..120 }
    }
    val fallbackMaxHeartRate = fallbackAge?.let(::getMaxHeartRate)

    suspend fun loadRestingHeartRateWithMinimumLoadingTime(): Int? {
        val startedAt = System.currentTimeMillis()
        return try {
            getHistoricalRestingHeartRateFromHealthConnect(healthConnectClient)
        } finally {
            val elapsed = System.currentTimeMillis() - startedAt
            val remaining = 1000L - elapsed
            if (remaining > 0L) {
                delay(remaining)
            }
        }
    }

    suspend fun loadVo2MaxWithMinimumLoadingTime(): Double? {
        val startedAt = System.currentTimeMillis()
        return try {
            getHistoricalVo2MaxFromHealthConnect(healthConnectClient)
        } finally {
            val elapsed = System.currentTimeMillis() - startedAt
            val remaining = 1000L - elapsed
            if (remaining > 0L) {
                delay(remaining)
            }
        }
    }

    // Fills the height/weight editors from the latest Health Connect measurements; the values
    // persist (and sync to the watch) through the normal Save flow. Only fields with an actual
    // record are touched, so a missing record never clears an existing value.
    suspend fun populateBodyMeasurementsFromHealthConnect() {
        val startedAt = System.currentTimeMillis()
        try {
            if (HealthConnectClient.getSdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) {
                Toast.makeText(
                    context,
                    context.getString(R.string.settings_hc_unavailable),
                    Toast.LENGTH_SHORT
                ).show()
                return
            }
            val grantedPermissions = try {
                healthConnectClient.permissionController.getGrantedPermissions()
            } catch (_: Exception) {
                emptySet()
            }
            val canReadHeight = grantedPermissions.contains(HealthPermission.getReadPermission(HeightRecord::class))
            val canReadWeight = grantedPermissions.contains(HealthPermission.getReadPermission(WeightRecord::class))
            if (!canReadHeight && !canReadWeight) {
                Toast.makeText(
                    context,
                    context.getString(R.string.settings_hc_permissions_missing),
                    Toast.LENGTH_SHORT
                ).show()
                return
            }

            val measurements = getLatestBodyMeasurementsFromHealthConnect(healthConnectClient)
            var filledAny = false
            measurements.heightCm?.let {
                heightState.value = it.toString()
                filledAny = true
            }
            measurements.weightKg?.let {
                weightState.value = it.toString()
                filledAny = true
            }
            Toast.makeText(
                context,
                if (filledAny) {
                    context.getString(R.string.settings_body_loaded)
                } else {
                    context.getString(R.string.settings_body_not_found)
                },
                Toast.LENGTH_SHORT
            ).show()
        } catch (_: Exception) {
            Toast.makeText(
                context,
                context.getString(R.string.settings_body_read_failed),
                Toast.LENGTH_SHORT
            ).show()
        } finally {
            val elapsed = System.currentTimeMillis() - startedAt
            val remaining = 1000L - elapsed
            if (remaining > 0L) {
                delay(remaining)
            }
            isLoadingBodyMeasurements = false
        }
    }

    val bodyMeasurementPermissions = remember {
        setOf(
            HealthPermission.getReadPermission(HeightRecord::class),
            HealthPermission.getReadPermission(WeightRecord::class)
        )
    }

    val bodyMeasurementPermissionLauncher = rememberLauncherForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) {
        coroutineScope.launch {
            isLoadingBodyMeasurements = true
            populateBodyMeasurementsFromHealthConnect()
        }
    }
    
    LaunchedEffect(Unit) {
        if (workoutStore.restingHeartRate == null && !canUseHealthConnect) {
            // Not this profile's provider: show the default instead of another person's value.
            restingHeartRateState.value = defaultRestingHeartRate.toString()
        } else if (workoutStore.restingHeartRate == null) {
            isLoadingRestingHeartRate = true
            try {
                val historicalRestingHeartRate =
                    loadRestingHeartRateWithMinimumLoadingTime()
                if (historicalRestingHeartRate != null) {
                    restingHeartRateState.value = historicalRestingHeartRate.toString()
                } else {
                    restingHeartRateState.value = defaultRestingHeartRate.toString()
                }
            } catch (_: Exception) {
                restingHeartRateState.value = defaultRestingHeartRate.toString()
            } finally {
                isLoadingRestingHeartRate = false
            }
        }
    }

    val outlineColor = MaterialTheme.colorScheme.outlineVariant

    BreadcrumbScaffold(
        topBar = {
            TopAppBar(
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
                        text = stringResource(R.string.settings_title),
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onCancel, enabled = !isSaving) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.common_back)
                        )
                    }
                },
                actions = {
                    // Invisible icon to balance the title correctly
                    IconButton(modifier = Modifier.alpha(0f), onClick = { /* No-op */ }) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = null
                        )
                    }
                }
            )
        }
    ) { paddingValues ->
        val scrollState = rememberScrollState()

        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(vertical = Spacing.md)
                .verticalScroll(scrollState)
                .padding(horizontal = Spacing.md)
        ) {
            FormSectionTitle(stringResource(R.string.settings_user_profiles))
            UserProfilesCard(onHealthConnectOwnerChanged = { healthConnectRevision++ })

            FormSectionTitle(stringResource(R.string.settings_body_metrics), modifier = Modifier.padding(top = Spacing.lg))
            val activeProfileName = remember(context) { Profiles.activeProfile(context).name }
            ContentSubtitle(
                text = stringResource(R.string.settings_profile_values_only, activeProfileName),
                modifier = Modifier.padding(bottom = Spacing.md)
            )
            StyledCard(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(Spacing.md)) {
                    OutlinedTextField(
                        value = birthDateYearState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                birthDateYearState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_year_of_birth)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = weightState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || (input.count { it == '.' } <= 1 && input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                                weightState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_weight_kg)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = heightState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                heightState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_height_cm)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    ContentSubtitle(
                        text = stringResource(R.string.settings_height_hint),
                        modifier = Modifier.padding(vertical = Spacing.xs)
                    )
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs),
                        horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                    ) {
                        AppPrimaryOutlinedButton(
                            text = if (genderState.value == 0) {
                                stringResource(R.string.settings_male_checked)
                            } else {
                                stringResource(R.string.settings_male)
                            },
                            onClick = {
                                genderState.value = if (genderState.value == 0) null else 0
                            },
                            textAlign = TextAlign.Center,
                            modifier = Modifier.weight(1f)
                        )
                        AppPrimaryOutlinedButton(
                            text = if (genderState.value == 1) {
                                stringResource(R.string.settings_female_checked)
                            } else {
                                stringResource(R.string.settings_female)
                            },
                            onClick = {
                                genderState.value = if (genderState.value == 1) null else 1
                            },
                            textAlign = TextAlign.Center,
                            modifier = Modifier.weight(1f)
                        )
                    }
                    // Full width on its own row: three buttons in one row left no room for the
                    // label and wrapped it onto multiple lines.
                    AppPrimaryOutlinedButton(
                        text = if (genderState.value == null) {
                            stringResource(R.string.settings_unspecified_checked)
                        } else {
                            stringResource(R.string.settings_unspecified)
                        },
                        onClick = {
                            genderState.value = null
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(top = Spacing.xs)
                    )

                    if (canUseHealthConnect) AppPrimaryOutlinedButton(
                        text = if (isLoadingBodyMeasurements) {
                            stringResource(R.string.settings_loading_hc)
                        } else {
                            stringResource(R.string.settings_fill_from_hc)
                        },
                        onClick = {
                            if (isLoadingBodyMeasurements) {
                                return@AppPrimaryOutlinedButton
                            }
                            coroutineScope.launch {
                                val missingPermissions = try {
                                    bodyMeasurementPermissions -
                                        healthConnectClient.permissionController.getGrantedPermissions()
                                } catch (_: Exception) {
                                    bodyMeasurementPermissions
                                }
                                if (missingPermissions.isEmpty()) {
                                    isLoadingBodyMeasurements = true
                                    populateBodyMeasurementsFromHealthConnect()
                                } else {
                                    bodyMeasurementPermissionLauncher.launch(missingPermissions)
                                }
                            }
                        },
                        enabled = !isLoadingBodyMeasurements,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )
                    ContentSubtitle(
                        text = stringResource(R.string.settings_fill_hc_hint),
                        modifier = Modifier.padding(vertical = Spacing.xs)
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle(stringResource(R.string.settings_plans_on_watch), modifier = Modifier.padding(top = Spacing.lg))
            StyledCard(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(Spacing.md)) {
                    ContentSubtitle(
                        text = stringResource(R.string.settings_plans_hint),
                        modifier = Modifier.padding(bottom = Spacing.xs)
                    )
                    workoutStore.workoutPlans
                        .sortedWith(compareBy({ it.name == UNASSIGNED_PLAN_NAME }, { it.order }, { it.name }))
                        .forEach { plan ->
                            val selectedIds = visiblePlanIdsState.value
                            val checked = selectedIds == null || plan.id in selectedIds
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clickable {
                                        val current = visiblePlanIdsState.value ?: workoutStore.workoutPlans.map { it.id }.toSet()
                                        val next = if (plan.id in current) current - plan.id else current + plan.id
                                        // An empty selection would leave the watch with nothing to do.
                                        visiblePlanIdsState.value = next.ifEmpty { null }
                                    }
                                    .padding(vertical = Spacing.xs),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                            ) {
                                Checkbox(
                                    checked = checked,
                                    onCheckedChange = null
                                )
                                Text(
                                    text = plan.name,
                                    style = MaterialTheme.typography.bodyLarge,
                                    modifier = Modifier.weight(1f)
                                )
                            }
                        }
                }
            }

            FormSectionTitle(stringResource(R.string.settings_heart_rate))
            StyledCard(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(Spacing.md)) {
                    OutlinedTextField(
                        value = measuredMaxHeartRateState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                measuredMaxHeartRateState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_measured_hr_max)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )
                    ContentSubtitle(
                        text = if (fallbackAge != null && fallbackMaxHeartRate != null) {
                            stringResource(R.string.settings_hr_max_formula_with_age, fallbackAge, fallbackMaxHeartRate)
                        } else {
                            stringResource(R.string.settings_hr_max_formula)
                        },
                        modifier = Modifier.padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = restingHeartRateState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                restingHeartRateState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_resting_hr)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    if (canUseHealthConnect) AppPrimaryOutlinedButton(
                        text = if (isLoadingRestingHeartRate) {
                            stringResource(R.string.settings_loading_rhr)
                        } else {
                            stringResource(R.string.settings_use_hc_value)
                        },
                        onClick = {
                            if (isLoadingRestingHeartRate) {
                                return@AppPrimaryOutlinedButton
                            }
                            coroutineScope.launch {
                                isLoadingRestingHeartRate = true
                                try {
                                    val historicalRestingHeartRate =
                                        loadRestingHeartRateWithMinimumLoadingTime()
                                    if (historicalRestingHeartRate != null) {
                                        restingHeartRateState.value = historicalRestingHeartRate.toString()
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.settings_rhr_loaded),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } else {
                                        restingHeartRateState.value = defaultRestingHeartRate.toString()
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.settings_rhr_not_found, defaultRestingHeartRate),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                } catch (_: Exception) {
                                    restingHeartRateState.value = defaultRestingHeartRate.toString()
                                    Toast.makeText(
                                        context,
                                        context.getString(R.string.settings_rhr_read_failed, defaultRestingHeartRate),
                                        Toast.LENGTH_SHORT
                                    ).show()
                                } finally {
                                    isLoadingRestingHeartRate = false
                                }
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = vo2MaxState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || (input.count { it == '.' } <= 1 && input.all { it.isDigit() || it == '.' } && !input.startsWith("."))) {
                                vo2MaxState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_vo2max_label)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )
                    ContentSubtitle(
                        text = stringResource(R.string.settings_vo2max_hint),
                        modifier = Modifier.padding(vertical = Spacing.xs)
                    )

                    if (canUseHealthConnect) AppPrimaryOutlinedButton(
                        text = if (isLoadingVo2Max) {
                            stringResource(R.string.settings_loading_vo2max)
                        } else {
                            stringResource(R.string.settings_use_hc_value)
                        },
                        onClick = {
                            if (isLoadingVo2Max) {
                                return@AppPrimaryOutlinedButton
                            }
                            coroutineScope.launch {
                                isLoadingVo2Max = true
                                try {
                                    val historicalVo2Max = loadVo2MaxWithMinimumLoadingTime()
                                    if (historicalVo2Max != null) {
                                        vo2MaxState.value = historicalVo2Max.toString()
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.settings_vo2max_loaded),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    } else {
                                        Toast.makeText(
                                            context,
                                            context.getString(R.string.settings_vo2max_not_found),
                                            Toast.LENGTH_SHORT
                                        ).show()
                                    }
                                } catch (_: Exception) {
                                    Toast.makeText(
                                        context,
                                        context.getString(R.string.settings_vo2max_read_failed),
                                        Toast.LENGTH_SHORT
                                    ).show()
                                } finally {
                                    isLoadingVo2Max = false
                                }
                            }
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle(stringResource(R.string.settings_training_progression))
            StyledCard(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(Spacing.md)) {
                    ContentSubtitle(
                        text = stringResource(R.string.settings_distance_units_hint),
                        modifier = Modifier.padding(vertical = Spacing.xs)
                    )
                    listOf(
                        DistanceUnit.KILOMETERS to stringResource(R.string.settings_km),
                        DistanceUnit.MILES to stringResource(R.string.settings_mi)
                    ).forEach { (unit, label) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .selectable(
                                    selected = distanceUnitState.value == unit,
                                    onClick = { distanceUnitState.value = unit }
                                ),
                            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                        ) {
                            RadioButton(
                                selected = distanceUnitState.value == unit,
                                onClick = { distanceUnitState.value = unit }
                            )
                            Text(label)
                        }
                    }
                    ContentSubtitle(
                        text = stringResource(R.string.settings_deload_defaults_hint),
                        modifier = Modifier.padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = deloadFailedSessionsThresholdState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                deloadFailedSessionsThresholdState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_failed_sessions_threshold)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = deloadCompletedSessionsIntervalState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                deloadCompletedSessionsIntervalState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_completed_sessions_interval)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = deloadWeightFactorState.value,
                        onValueChange = { input ->
                            if (
                                input.isEmpty() ||
                                (input.count { it == '.' } <= 1 &&
                                    input.all { it.isDigit() || it == '.' } &&
                                    !input.startsWith("."))
                            ) {
                                deloadWeightFactorState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_deload_weight_factor)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = deloadRepsDropState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                deloadRepsDropState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_deload_reps_drop)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = deloadCutSetsToState.value,
                        onValueChange = { input ->
                            if (input.isEmpty() || input.all { it.isDigit() }) {
                                deloadCutSetsToState.value = input
                            }
                        },
                        label = { Text(stringResource(R.string.settings_cut_sets_to)) },
                        keyboardOptions = KeyboardOptions.Default.copy(keyboardType = KeyboardType.Number),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle(stringResource(R.string.settings_external_sensors))
            StyledCard(
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(Spacing.md)) {
                    OutlinedTextField(
                        value = polarDeviceIdState.value,
                        onValueChange = { polarDeviceIdState.value = it },
                        label = { Text(stringResource(R.string.settings_polar_device_id)) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = polarDisplayNameState.value,
                        onValueChange = { polarDisplayNameState.value = it },
                        label = { Text(stringResource(R.string.settings_polar_display_name)) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = whoopDeviceIdState.value,
                        onValueChange = { whoopDeviceIdState.value = it },
                        label = { Text(stringResource(R.string.settings_whoop_device_id)) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )

                    OutlinedTextField(
                        value = whoopDisplayNameState.value,
                        onValueChange = { whoopDisplayNameState.value = it },
                        label = { Text(stringResource(R.string.settings_whoop_display_name)) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                    )
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            FormSectionTitle(stringResource(R.string.settings_ai))
            StyledCard(
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(Spacing.md)
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(
                            text = stringResource(R.string.settings_enable_ai),
                            style = MaterialTheme.typography.bodyLarge
                        )
                        ContentSubtitle(
                            text = stringResource(R.string.settings_enable_ai_hint)
                        )
                    }
                    Switch(
                        checked = mobileLlmEnabledState.value,
                        onCheckedChange = { mobileLlmEnabledState.value = it },
                        enabled = !isImportingLiteRtModel
                    )
                }
            }
            if (mobileLlmEnabledState.value) {
                Spacer(modifier = Modifier.height(Spacing.sm))
                FormSectionTitle(stringResource(R.string.settings_workout_insights))
                StyledCard(
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(Spacing.md)) {
                        ContentSubtitle(
                            text = stringResource(R.string.settings_insights_mode_hint),
                            modifier = Modifier.padding(vertical = Spacing.xs)
                        )
                        WorkoutInsightsMode.entries.forEach { mode ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .selectable(
                                        selected = workoutInsightsModeState.value == mode,
                                        enabled = !isImportingLiteRtModel,
                                        onClick = { workoutInsightsModeState.value = mode }
                                    )
                                    .padding(horizontal = 8.dp, vertical = 4.dp),
                                horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                            ) {
                                RadioButton(
                                    selected = workoutInsightsModeState.value == mode,
                                    onClick = null,
                                    enabled = !isImportingLiteRtModel
                                )
                                Column(modifier = Modifier.fillMaxWidth()) {
                                    Text(
                                        text = mode.label,
                                        style = MaterialTheme.typography.bodyLarge
                                    )
                                    ContentSubtitle(
                                        text = if (mode == WorkoutInsightsMode.LOCAL) {
                                            stringResource(R.string.settings_mode_local_desc)
                                        } else {
                                            stringResource(R.string.settings_mode_remote_desc)
                                        }
                                    )
                                }
                            }
                        }

                        if (workoutInsightsModeState.value == WorkoutInsightsMode.LOCAL) {
                            OutlinedTextField(
                                value = liteRtModelName.orEmpty(),
                                onValueChange = {},
                                readOnly = true,
                                label = { Text(stringResource(R.string.settings_litert_model)) },
                                placeholder = { Text(stringResource(R.string.settings_no_model_selected)) },
                                modifier = Modifier
                                    .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                            )

                            ContentSubtitle(
                                text = stringResource(R.string.settings_backend_hint),
                                modifier = Modifier.padding(vertical = Spacing.xs)
                            )

                            LiteRtLmBackendPreference.entries.forEach { preference ->
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .selectable(
                                            selected = liteRtBackendPreferenceState.value == preference,
                                            enabled = !isImportingLiteRtModel,
                                            onClick = { liteRtBackendPreferenceState.value = preference }
                                        )
                                        .padding(horizontal = 8.dp, vertical = 4.dp),
                                    horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
                                ) {
                                    RadioButton(
                                        selected = liteRtBackendPreferenceState.value == preference,
                                        onClick = null,
                                        enabled = !isImportingLiteRtModel
                                    )
                                    Column(modifier = Modifier.fillMaxWidth()) {
                                        Text(
                                            text = preference.label,
                                            style = MaterialTheme.typography.bodyLarge
                                        )
                                    }
                                }
                            }

                            AppPrimaryOutlinedButton(
                                text = if (liteRtModelPath == null) {
                                    stringResource(R.string.settings_import_model)
                                } else {
                                    stringResource(R.string.settings_replace_model)
                                },
                                onClick = onImportLiteRtModel,
                                enabled = !isImportingLiteRtModel,
                                modifier = Modifier
                                    .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                            )

                            AppSecondaryButton(
                                text = stringResource(R.string.settings_clear_model),
                                onClick = onClearLiteRtModel,
                                enabled = liteRtModelPath != null && !isImportingLiteRtModel,
                                modifier = Modifier
                                    .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                            )
                        } else {
                            OutlinedTextField(
                                value = remoteBaseUrlState.value,
                                onValueChange = { remoteBaseUrlState.value = it },
                                label = { Text(stringResource(R.string.settings_remote_base_url)) },
                                placeholder = { Text(stringResource(R.string.settings_remote_url_placeholder)) },
                                modifier = Modifier
                                    .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                            )

                            OutlinedTextField(
                                value = remoteApiKeyState.value,
                                onValueChange = { remoteApiKeyState.value = it },
                                label = { Text(stringResource(R.string.settings_remote_api_key)) },
                                placeholder = { Text(stringResource(R.string.settings_api_key_placeholder)) },
                                modifier = Modifier
                                    .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                            )

                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = Spacing.xs)
                            ) {
                                AppSecondaryButton(
                                    text = when {
                                        isFetchingRemoteModels -> stringResource(R.string.settings_loading_models)
                                        remoteModels.isEmpty() -> stringResource(R.string.settings_load_models)
                                        else -> stringResource(R.string.settings_choose_model, remoteModels.size)
                                    },
                                    onClick = {
                                        if (remoteModels.isEmpty()) {
                                            loadRemoteModels()
                                        } else {
                                            remoteModelsMenuExpanded = true
                                        }
                                    },
                                    enabled = !isFetchingRemoteModels,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                DropdownMenu(
                                    expanded = remoteModelsMenuExpanded,
                                    onDismissRequest = { remoteModelsMenuExpanded = false },
                                ) {
                                    DropdownMenuItem(
                                        text = { Text(stringResource(R.string.settings_reload_models)) },
                                        onClick = {
                                            remoteModelsMenuExpanded = false
                                            loadRemoteModels()
                                        },
                                    )
                                    remoteModels.forEach { modelId ->
                                        DropdownMenuItem(
                                            text = { Text(modelId) },
                                            onClick = {
                                                remoteModelState.value = modelId
                                                remoteModelsMenuExpanded = false
                                            },
                                        )
                                    }
                                }
                            }

                            remoteModelsError?.let { error ->
                                Text(
                                    text = error,
                                    color = MaterialTheme.colorScheme.error,
                                    style = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(vertical = Spacing.xs)
                                )
                            }

                            OutlinedTextField(
                                value = remoteModelState.value,
                                onValueChange = { remoteModelState.value = it },
                                label = { Text(stringResource(R.string.settings_remote_model)) },
                                placeholder = { Text(stringResource(R.string.settings_remote_model_placeholder)) },
                                modifier = Modifier
                                    .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                            )

                            ContentSubtitle(
                                text = stringResource(R.string.settings_models_endpoint_hint),
                                modifier = Modifier.padding(vertical = Spacing.xs)
                            )
                        }

                        OutlinedTextField(
                            value = workoutInsightsCustomInstructionsState.value,
                            onValueChange = { workoutInsightsCustomInstructionsState.value = it },
                            label = { Text(stringResource(R.string.settings_insight_instructions)) },
                            placeholder = { Text(stringResource(R.string.settings_insight_instructions_placeholder)) },
                            minLines = 3,
                            maxLines = 6,
                            modifier = Modifier
                                .fillMaxWidth()
                            .padding(vertical = Spacing.xs)
                        )
                        ContentSubtitle(
                            text = stringResource(R.string.settings_insight_instructions_hint),
                            modifier = Modifier.padding(vertical = Spacing.xs)
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(Spacing.sm))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = Spacing.md),
                horizontalArrangement = Arrangement.spacedBy(Spacing.sm)
            ) {
                AppSecondaryButton(
                    text = stringResource(R.string.common_cancel),
                    onClick = onCancel,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f)
                )

                AppPrimaryButton(
                    onClick = {
                        val birthDateYear = birthDateYearState.value.toIntOrNull()
                        val currentYear = Calendar.getInstance().get(Calendar.YEAR)

                        if (birthDateYear == null || birthDateYear < 1900 || birthDateYear > currentYear) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_birth_year), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val weight = weightState.value.toDoubleOrNull()
                        if (weight == null || weight !in 20.0..400.0) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_weight), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val heightCm = heightState.value.toIntOrNull()
                        if (heightState.value.isNotBlank() &&
                            (heightCm == null || heightCm !in 80..250)
                        ) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_height), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val measuredMaxHeartRate = measuredMaxHeartRateState.value.toIntOrNull()
                        if (measuredMaxHeartRateState.value.isNotBlank() &&
                            (measuredMaxHeartRate == null || measuredMaxHeartRate !in 120..260)
                        ) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_hr_max), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val restingHeartRate = restingHeartRateState.value.toIntOrNull()
                            ?: getEffectiveRestingHeartRate()
                        if (restingHeartRate !in 30..120) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_rhr), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val vo2Max = vo2MaxState.value.toDoubleOrNull()
                        if (vo2MaxState.value.isNotBlank() &&
                            (vo2Max == null || vo2Max !in 10.0..95.0)
                        ) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_vo2max), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }
                        val vo2MaxChanged = vo2Max != workoutStore.estimatedVo2MaxMlKgMin
                        val newVo2MaxSource = when {
                            vo2Max == null -> null
                            vo2MaxChanged -> "USER"
                            else -> workoutStore.vo2MaxSource
                        }
                        val newVo2MaxEstimatedAtEpochDay = when {
                            vo2Max == null -> null
                            vo2MaxChanged -> LocalDate.now().toEpochDay()
                            else -> workoutStore.vo2MaxEstimatedAtEpochDay
                        }
                        val deloadFailedSessionsThreshold =
                            deloadFailedSessionsThresholdState.value.toIntOrNull()
                        if (deloadFailedSessionsThresholdState.value.isNotBlank() &&
                            (deloadFailedSessionsThreshold == null || deloadFailedSessionsThreshold < 1)
                        ) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_failed_threshold), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }
                        val deloadCompletedSessionsInterval =
                            deloadCompletedSessionsIntervalState.value.toIntOrNull()
                        if (deloadCompletedSessionsIntervalState.value.isNotBlank() &&
                            (deloadCompletedSessionsInterval == null || deloadCompletedSessionsInterval < 1)
                        ) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_completed_interval), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }
                        val deloadWeightFactor = deloadWeightFactorState.value.toDoubleOrNull()
                        if (deloadWeightFactor == null || deloadWeightFactor <= 0.0 || deloadWeightFactor > 1.0) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_weight_factor), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }
                        val deloadRepsDrop = deloadRepsDropState.value.toIntOrNull()
                        if (deloadRepsDrop == null || deloadRepsDrop < 0) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_reps_drop), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }
                        val deloadCutSetsTo = deloadCutSetsToState.value.toIntOrNull()
                        if (deloadCutSetsToState.value.isNotBlank() &&
                            (deloadCutSetsTo == null || deloadCutSetsTo < 1)
                        ) {
                            Toast.makeText(context, context.getString(R.string.settings_invalid_cut_sets), Toast.LENGTH_SHORT).show()
                            return@AppPrimaryButton
                        }

                        val externalHeartRateConfigs = buildList {
                            val polarDeviceId = polarDeviceIdState.value.trim()
                            if (polarDeviceId.isNotEmpty()) {
                                add(
                                    PolarHeartRateConfig(
                                        deviceId = polarDeviceId,
                                        displayName = polarDisplayNameState.value.trim().ifBlank { null }
                                    )
                                )
                            }

                            val whoopDeviceId = whoopDeviceIdState.value.trim().ifBlank { null }
                            val whoopDisplayName = whoopDisplayNameState.value.trim().ifBlank { null }
                            if (whoopDeviceId != null || whoopDisplayName != null) {
                                add(
                                    WhoopHeartRateConfig(
                                        deviceId = whoopDeviceId,
                                        displayName = whoopDisplayName
                                    )
                                )
                            }
                        }

                        val newWorkoutStore = workoutStore.copy(
                            externalHeartRateConfigs = externalHeartRateConfigs,
                            birthDateYear = birthDateYear,
                            weightKg = weight,
                            heightCm = heightCm,
                            deloadConfig = DeloadConfig(
                                failedSessionsThreshold = deloadFailedSessionsThreshold,
                                completedSessionsInterval = deloadCompletedSessionsInterval,
                                weightFactor = deloadWeightFactor,
                                repsDrop = deloadRepsDrop,
                                cutSetsTo = deloadCutSetsTo
                            ),
                            measuredMaxHeartRate = measuredMaxHeartRate,
                            restingHeartRate = restingHeartRate,
                            gender = genderState.value,
                            // Keep the legacy calorie-engine flag in step with gender
                            // (true = female, false = male, null = unset).
                            sex = genderState.value?.let { it == 1 },
                            estimatedVo2MaxMlKgMin = vo2Max,
                            vo2MaxSource = newVo2MaxSource,
                            vo2MaxEstimatedAtEpochDay = newVo2MaxEstimatedAtEpochDay,
                            distanceUnit = distanceUnitState.value,
                            visibleWorkoutPlanIds = visiblePlanIdsState.value?.toList()
                        )
                        onSaveInsightsSettings(
                            mobileLlmEnabledState.value,
                            workoutInsightsModeState.value,
                            liteRtBackendPreferenceState.value,
                            RemoteOpenAiConfig(
                                    baseUrl = remoteBaseUrlState.value,
                                    apiKey = remoteApiKeyState.value,
                                    model = remoteModelState.value,
                                ),
                                workoutInsightsCustomInstructionsState.value
                        )
                        onSave(newWorkoutStore)
                    },
                    text = stringResource(R.string.common_save),
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }

    LoadingOverlay(
        isVisible = rememberDebouncedSavingVisible(isSaving || isImportingLiteRtModel),
        text = if (isImportingLiteRtModel) {
            context.getString(R.string.settings_importing_model)
        } else {
            context.getString(R.string.common_saving)
        }
    )
}
