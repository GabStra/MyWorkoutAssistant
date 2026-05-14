"""Large constant definitions for workout generator."""

import copy
import json

PLACEHOLDER_OR_UUID_PATTERN = (
    r"^(?:"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|(?:EQUIPMENT_|ACCESSORY_|EXERCISE_|SET_|WORKOUT_|COMPONENT_|REST_)[A-Za-z0-9_]+(?:_GLOBAL)?"
    r"|EXERCISE_WARMUP|SET_WARMUP"
    r")$"
)

JSON_SCHEMA = {                                                                                                                                                                                                                                  
    "$schema": "https://json-schema.org/draft/2020-12/schema",                                                                                                                                                                                   
    "title": "WorkoutPlanPackage",                                                                                                                                                                                                               
    "type": "object",                                                                                                                                                                                                                            
    "additionalProperties": False,                                                                                                                                                                                                               
    "required": [                                                                                                                                                                                                                                
        "name",
        "workouts",                                                                                                                                                                                                                              
        "equipments",
        "accessoryEquipments",
    ],
    "properties": {                                                                                                                                                                                                                              
        "name": {"type": "string"},
        "workouts": {"type": "array", "items": {"$ref": "#/$defs/Workout"}},                                                                                                                                                                    
        "equipments": {"type": "array", "items": {"$ref": "#/$defs/Equipment"}},                                                                                                                                                                
        "accessoryEquipments": {"type": "array", "items": {"$ref": "#/$defs/EquipmentAccessory"}},
    },
    "$defs": {                                                                                                                                                                                                                                   
        "UUID": {                                                                                                                                                                                                                                
            "type": "string",                                                                                                                                                                                                                    
            "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"                                                                                                                                           
        },                                                                                                                                                                                                                                       
        "LocalDate": {                                                                                                                                                                                                                           
            "type": "string",                                                                                                                                                                                                                    
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$"                                                                                                                                                                                                  
        },                                                                                                                                                                                                                                       
        "SetSubCategory": {                                                                                                                                                                                                                      
            "type": "string",                                                                                                                                                                                                                    
            "enum": ["WorkSet", "WarmupSet", "RestPauseSet", "BackOffSet", "CalibrationPendingSet", "CalibrationSet"]
        },                                                                                                                                                                                                                                       
        "ExerciseType": {                                                                                                                                                                                                                        
            "type": "string",                                                                                                                                                                                                                    
            "enum": ["COUNTUP", "BODY_WEIGHT", "COUNTDOWN", "WEIGHT"]                                                                                                                                                                            
        },                                                                                                                                                                                                                                       
        "ProgressionMode": {
            "type": "string",
            "enum": ["OFF", "DOUBLE_PROGRESSION", "AUTO_REGULATION"]
        },
        "ExerciseCategory": {
            "type": "string",
            "enum": ["HEAVY_COMPOUND", "MODERATE_COMPOUND", "ISOLATION"]
        },
        "MuscleGroup": {                                                                                                                                                                                                                         
            "type": "string",                                                                                                                                                                                                                    
            "enum": [                                                                                                                                                                                                                            
                "FRONT_ABS",                                                                                                                                                                                                                     
                "FRONT_ADDUCTORS",                                                                                                                                                                                                               
                "FRONT_ANKLES",                                                                                                                                                                                                                  
                "FRONT_BICEPS",                                                                                                                                                                                                                  
                "FRONT_CALVES",                                                                                                                                                                                                                  
                "FRONT_CHEST",                                                                                                                                                                                                                   
                "FRONT_DELTOIDS",
                "FRONT_FEET",                                                                                                                                                                                                                    
                "FRONT_FOREARM",                                                                                                                                                                                                                 
                "FRONT_HANDS",                                                                                                                                                                                                                   
                "FRONT_KNEES",                                                                                                                                                                                                                   
                "FRONT_NECK",                                                                                                                                                                                                                    
                "FRONT_OBLIQUES",                                                                                                                                                                                                                
                "FRONT_QUADRICEPS",                                                                                                                                                                                                              
                "FRONT_TIBIALIS",                                                                                                                                                                                                                
                "FRONT_TRAPEZIUS",                                                                                                                                                                                                               
                "FRONT_TRICEPS",                                                                                                                                                                                                                 
                "BACK_ADDUCTORS",                                                                                                                                                                                                                
                "BACK_ANKLES",                                                                                                                                                                                                                   
                "BACK_CALVES",                                                                                                                                                                                                                   
                "BACK_DELTOIDS",                                                                                                                                                                                                                 
                "BACK_FEET",                                                                                                                                                                                                                     
                "BACK_FOREARM",                                                                                                                                                                                                                  
                "BACK_GLUTEAL",                                                                                                                                                                                                                  
                "BACK_HAMSTRING",                                                                                                                                                                                                                
                "BACK_HANDS",                                                                                                                                                                                                                    
                "BACK_LOWER_BACK",                                                                                                                                                                                                               
                "BACK_NECK",                                                                                                                                                                                                                     
                "BACK_TRAPEZIUS",                                                                                                                                                                                                                
                "BACK_TRICEPS",                                                                                                                                                                                                                  
                "BACK_UPPER_BACK"                                                                                                                                                                                                                
            ]                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "BaseWeight": {                                                                                                                                                                                                                          
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["weight"],                                                                                                                                                                                                              
            "properties": {"weight": {"type": "number"}}                                                                                                                                                                                         
        },                                                                                                                                                                                                                                       
        # Plate: thickness is in millimeters (mm)
        "Plate": {
            "type": "object",
            "additionalProperties": False,
            "required": ["weight", "thickness"],
            "properties": {
                "weight": {"type": "number"},
                "thickness": {"type": "number"}  # in millimeters (mm)
            }
        },
        "WeightSet": {                                                                                                                                                                                                                           
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "reps", "weight", "subCategory"],                                                                                                                                                                         
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "WeightSet"},                                                                                                                                                                                                  
                "reps": {"type": "integer"},                                                                                                                                                                                                     
                "weight": {"type": "number"},                                                                                                                                                                                                    
                "subCategory": {"$ref": "#/$defs/SetSubCategory"}                                                                                                                                                                                
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "BodyWeightSet": {                                                                                                                                                                                                                       
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "reps", "additionalWeight", "subCategory"],                                                                                                                                                               
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "BodyWeightSet"},                                                                                                                                                                                              
                "reps": {"type": "integer"},                                                                                                                                                                                                     
                "additionalWeight": {"type": "number"},                                                                                                                                                                                          
                "subCategory": {"$ref": "#/$defs/SetSubCategory"}
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "TimedDurationSet": {                                                                                                                                                                                                                    
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "timeInMillis", "autoStart", "autoStop"],                                                                                                                                                                 
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "TimedDurationSet"},                                                                                                                                                                                           
                "timeInMillis": {"type": "integer"},                                                                                                                                                                                             
                "autoStart": {"type": "boolean"},                                                                                                                                                                                                
                "autoStop": {"type": "boolean"}                                                                                                                                                                                                  
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "EnduranceSet": {                                                                                                                                                                                                                        
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "timeInMillis", "autoStart", "autoStop"],                                                                                                                                                                 
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "EnduranceSet"},                                                                                                                                                                                               
                "timeInMillis": {"type": "integer"},                                                                                                                                                                                             
                "autoStart": {"type": "boolean"},                                                                                                                                                                                                
                "autoStop": {"type": "boolean"}                                                                                                                                                                                                  
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "RestSet": {                                                                                                                                                                                                                             
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "timeInSeconds", "subCategory"],                                                                                                                                                                          
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "RestSet"},                                                                                                                                                                                                    
                "timeInSeconds": {"type": "integer"},                                                                                                                                                                                            
                "subCategory": {"$ref": "#/$defs/SetSubCategory"}                                                                                                                                                                                
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Set": {                                                                                                                                                                                                                                 
            "oneOf": [                                                                                                                                                                                                                           
                {"$ref": "#/$defs/WeightSet"},                                                                                                                                                                                                   
                {"$ref": "#/$defs/BodyWeightSet"},                                                                                                                                                                                               
                {"$ref": "#/$defs/TimedDurationSet"},                                                                                                                                                                                            
                {"$ref": "#/$defs/EnduranceSet"},                                                                                                                                                                                                
                {"$ref": "#/$defs/RestSet"}                                                                                                                                                                                                      
            ]                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Exercise": {                                                                                                                                                                                                                            
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "enabled",                                                                                                                                                                                                                       
                "name",                                                                                                                                                                                                                          
                "notes",                                                                                                                                                                                                                         
                "sets",                                                                                                                                                                                                                          
                "exerciseType",                                                                                                                                                                                                                  
                "generateWarmUpSets",                                                                                                                                                                                                            
                "progressionMode",                                                                                                                                                                                                               
                "keepScreenOn",                                                                                                                                                                                                                  
                "showCountDownTimer",
                "requiresLoadCalibration"                                                                                                                                                                                                        
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "Exercise"},                                                                                                                                                                                                   
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "name": {"type": "string"},                                                                                                                                                                                                      
                "notes": {"type": "string", "maxLength": 500},                                                                                                                                                                                                     
                "sets": {"type": "array", "items": {"$ref": "#/$defs/Set"}},                                                                                                                                                                     
                "exerciseType": {"$ref": "#/$defs/ExerciseType"},                                                                                                                                                                                
                "minReps": {"type": "integer"},                                                                                                                                                                                                  
                "maxReps": {"type": "integer"},                                                                                                                                                                                                  
                "lowerBoundMaxHRPercent": {"type": ["number", "null"]},                                                                                                                                                                          
                "upperBoundMaxHRPercent": {"type": ["number", "null"]},                                                                                                                                                                          
                "equipmentId": {                                                                                                                                                                                                                 
                    "anyOf": [                                                                                                                                                                                                                   
                        {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                
                        {"type": "null"}                                                                                                                                                                                                         
                    ]                                                                                                                                                                                                                            
                },                                                                                                                                                                                                                               
                "bodyWeightPercentage": {"type": ["number", "null"]},                                                                                                                                                                            
                "generateWarmUpSets": {"type": "boolean"},                                                                                                                                                                                       
                "progressionMode": {"$ref": "#/$defs/ProgressionMode"},                                                                                                                                                                          
                "keepScreenOn": {"type": "boolean"},                                                                                                                                                                                             
                "showCountDownTimer": {"type": "boolean"},                                                                                                                                                                                       
                "intraSetRestInSeconds": {"type": ["integer", "null"]},                                                                                                                                                                          
                "loadJumpDefaultPct": {"type": ["number", "null"]},                                                                                                                                                                              
                "loadJumpMaxPct": {"type": ["number", "null"]},                                                                                                                                                                                  
                "loadJumpOvercapUntil": {"type": ["integer", "null"]},                                                                                                                                                                           
                "muscleGroups": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/MuscleGroup"},
                    "uniqueItems": True
                },
                "secondaryMuscleGroups": {                                                                                                                                                                                                       
                    "type": "array",                                                                                                                                                                                                             
                    "items": {"$ref": "#/$defs/MuscleGroup"},                                                                                                                                                                                    
                    "uniqueItems": True                                                                                                                                                                                                          
                },
                "requiredAccessoryEquipmentIds": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/UUID"},
                    "uniqueItems": True
                },
                "requiresLoadCalibration": {"type": "boolean"},
                "exerciseCategory": {
                    "oneOf": [
                        {"$ref": "#/$defs/ExerciseCategory"},
                        {"type": "null"}
                    ]
                }
            }                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "RestComponent": {
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "enabled", "timeInSeconds"],                                                                                                                                                                              
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "Rest"},                                                                                                                                                                                                       
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "timeInSeconds": {"type": "integer"}                                                                                                                                                                                             
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Superset": {                                                                                                                                                                                                                            
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "enabled", "exercises", "restSecondsByExercise"],                                                                                                                                                         
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "Superset"},                                                                                                                                                                                                   
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "exercises": {"type": "array", "items": {"$ref": "#/$defs/Exercise"}},                                                                                                                                                           
                "restSecondsByExercise": {                                                                                                                                                                                                       
                    "type": "object",                                                                                                                                                                                                            
                    "additionalProperties": {"type": "integer"}                                                                                                                                                                                  
                }                                                                                                                                                                                                                                
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "WorkoutComponent": {                                                                                                                                                                                                                    
            "oneOf": [                                                                                                                                                                                                                           
                {"$ref": "#/$defs/Exercise"},                                                                                                                                                                                                    
                {"$ref": "#/$defs/RestComponent"},                                                                                                                                                                                               
                {"$ref": "#/$defs/Superset"}                                                                                                                                                                                                     
            ]                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "Workout": {                                                                                                                                                                                                                             
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "name",                                                                                                                                                                                                                          
                "description",                                                                                                                                                                                                                   
                "workoutComponents",                                                                                                                                                                                                             
                "order",                                                                                                                                                                                                                         
                "enabled",                                                                                                                                                                                                                       
                "usePolarDevice",                                                                                                                                                                                                                
                "creationDate",                                                                                                                                                                                                                  
                "isActive",                                                                                                                                                                                                                      
                "globalId",                                                                                                                                                                                                                      
                "type"                                                                                                                                                                                                                           
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "name": {"type": "string"},                                                                                                                                                                                                      
                "description": {"type": "string", "maxLength": 50},                                                                                                                                                                                               
                "workoutComponents": {
                    "type": "array",
                    "items": {
                        "allOf": [
                            {"not": {"type": "null"}},
                            {"oneOf": [
                                {"$ref": "#/$defs/Exercise"},
                                {"$ref": "#/$defs/RestComponent"},
                                {"$ref": "#/$defs/Superset"}
                            ]}
                        ]
                    }
                },
                "order": {"type": "integer"},                                                                                                                                                                                                    
                "enabled": {"type": "boolean"},                                                                                                                                                                                                  
                "usePolarDevice": {"type": "boolean"},                                                                                                                                                                                           
                "creationDate": {"$ref": "#/$defs/LocalDate"},                                                                                                                                                                                   
                "previousVersionId": {                                                                                                                                                                                                           
                    "anyOf": [                                                                                                                                                                                                                   
                        {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                
                        {"type": "null"}                                                                                                                                                                                                         
                    ]                                                                                                                                                                                                                            
                },                                                                                                                                                                                                                               
                "nextVersionId": {                                                                                                                                                                                                               
                    "anyOf": [                                                                                                                                                                                                                   
                        {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                
                        {"type": "null"}                                                                                                                                                                                                         
                    ]                                                                                                                                                                                                                            
                },                                                                                                                                                                                                                               
                "isActive": {"type": "boolean"},                                                                                                                                                                                                 
                "timesCompletedInAWeek": {"type": ["integer", "null"]},                                                                                                                                                                          
                "globalId": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                            
                "type": {"type": "integer"},
                "workoutPlanId": {
                    "anyOf": [
                        {"$ref": "#/$defs/UUID"},
                        {"type": "null"}
                    ]
                }                                                                                                                                                                                                      
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "WorkoutPlan": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "name", "workoutIds", "order"],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "name": {"type": "string"},
                "workoutIds": {"type": "array", "items": {"$ref": "#/$defs/UUID"}},
                "order": {"type": "integer"}
            }
        },
        "WeeklyProgressOverride": {
            "type": "object",
            "additionalProperties": False,
            "required": ["weekStart", "includedWorkoutGlobalIds"],
            "properties": {
                "weekStart": {"$ref": "#/$defs/LocalDate"},
                "includedWorkoutGlobalIds": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/UUID"}
                }
            }
        },
        # EquipmentBarbell: sleeveLength is in millimeters (mm) - refers to sleeve length (where plates are loaded), not total barbell length
        "EquipmentBarbell": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name", "availablePlates", "barWeight"],
            "anyOf": [{"required": ["sleeveLength"]}, {"required": ["barLength"]}],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "BARBELL"},
                "name": {"type": "string"},
                "availablePlates": {"type": "array", "items": {"$ref": "#/$defs/Plate"}},
                "barWeight": {"type": "number"},
                "sleeveLength": {"type": "integer"},  # in millimeters (mm)
                "barLength": {"type": "integer"}  # deprecated alias for sleeveLength
            }
        },
        "EquipmentDumbbells": {                                                                                                                                                                                                                  
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "name",                                                                                                                                                                                                                          
                "maxExtraWeightsPerLoadingPoint",                                                                                                                                                                                                
                "extraWeights",                                                                                                                                                                                                                  
                "dumbbells"                                                                                                                                                                                                                      
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "DUMBBELLS"},                                                                                                                                                                                                  
                "name": {"type": "string"},                                                                                                                                                                                                      
                "maxExtraWeightsPerLoadingPoint": {"type": "integer"},                                                                                                                                                                           
                "extraWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}},                                                                                                                                                      
                "dumbbells": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "EquipmentDumbbell": {                                                                                                                                                                                                                   
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "name",                                                                                                                                                                                                                          
                "maxExtraWeightsPerLoadingPoint",                                                                                                                                                                                                
                "extraWeights",                                                                                                                                                                                                                  
                "dumbbells"                                                                                                                                                                                                                      
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "DUMBBELL"},                                                                                                                                                                                                   
                "name": {"type": "string"},                                                                                                                                                                                                      
                "maxExtraWeightsPerLoadingPoint": {"type": "integer"},                                                                                                                                                                           
                "extraWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}},                                                                                                                                                      
                "dumbbells": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}                                                                                                                                                          
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        # EquipmentPlateLoadedCable: sleeveLength is in millimeters (mm) - refers to sleeve length (where plates are loaded)
        "EquipmentPlateLoadedCable": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name", "availablePlates"],
            "anyOf": [{"required": ["sleeveLength"]}, {"required": ["barLength"]}],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "PLATELOADEDCABLE"},
                "name": {"type": "string"},
                "availablePlates": {"type": "array", "items": {"$ref": "#/$defs/Plate"}},
                "sleeveLength": {"type": "integer"},  # in millimeters (mm)
                "barLength": {"type": "integer"}  # deprecated alias for sleeveLength
            }
        },
        "EquipmentWeightVest": {                                                                                                                                                                                                                 
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": ["id", "type", "name", "availableWeights"],                                                                                                                                                                              
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},                                                                                                                                                                                                  
                "type": {"const": "WEIGHTVEST"},                                                                                                                                                                                                 
                "name": {"type": "string"},                                                                                                                                                                                                      
                "availableWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}                                                                                                                                                   
            }                                                                                                                                                                                                                                    
        },                                                                                                                                                                                                                                       
        "EquipmentMachine": {                                                                                                                                                                                                                    
            "type": "object",                                                                                                                                                                                                                    
            "additionalProperties": False,                                                                                                                                                                                                       
            "required": [                                                                                                                                                                                                                        
                "id",                                                                                                                                                                                                                            
                "type",                                                                                                                                                                                                                          
                "name",                                                                                                                                                                                                                          
                "availableWeights",                                                                                                                                                                                                              
                "maxExtraWeightsPerLoadingPoint",
                "extraWeights"                                                                                                                                                                                                                   
            ],                                                                                                                                                                                                                                   
            "properties": {                                                                                                                                                                                                                      
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "MACHINE"},                                                                                                                                                                                                    
                "name": {"type": "string"},                                                                                                                                                                                                      
                "availableWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}},                                                                                                                                                  
                "maxExtraWeightsPerLoadingPoint": {"type": "integer"},                                                                                                                                                                           
                "extraWeights": {"type": "array", "items": {"$ref": "#/$defs/BaseWeight"}}                                                                                                                                                       
            }                                                                                                                                                                                                                                    
        },
        "EquipmentAccessory": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "type", "name"],
            "properties": {
                "id": {"$ref": "#/$defs/UUID"},
                "type": {"const": "ACCESSORY"},
                "name": {"type": "string"}
            }
        },
        "Equipment": {
            "oneOf": [
                {"$ref": "#/$defs/EquipmentBarbell"},
                {"$ref": "#/$defs/EquipmentDumbbells"},                                                                                                                                                                                          
                {"$ref": "#/$defs/EquipmentDumbbell"},                                                                                                                                                                                           
                {"$ref": "#/$defs/EquipmentPlateLoadedCable"},                                                                                                                                                                                   
                {"$ref": "#/$defs/EquipmentWeightVest"},                                                                                                                                                                                         
                {"$ref": "#/$defs/EquipmentMachine"}                                                                                                                                                                                             
            ]                                                                                                                                                                                                                                    
        }                                                                                                                                                                                                                                        
    }                                                                                                                                                                                                                                            
}                                                                                                                                                                                                                                                
EXAMPLE_JSON = {                                                                                                                                                                                                                                 
    "workouts": [
        {                                                                                                                                                                                                                                        
            "id": "11111111-1111-1111-1111-111111111111",                                                                                                                                                                                        
            "name": "Example Workout",                                                                                                                                                                                                           
            "description": "Example description",                                                                                                                                                                                                
            "workoutComponents": [                                                                                                                                                                                                               
                {                                                                                                                                                                                                                                
                    "id": "22222222-2222-2222-2222-222222222222",                                                                                                                                                                                
                    "type": "Exercise",                                                                                                                                                                                                          
                    "enabled": True,                                                                                                                                                                                                             
                    "name": "Back Squat",                                                                                                                                                                                                        
                    "notes": "",
                    "sets": [                                                                                                                                                                                                                    
                        {                                                                                                                                                                                                                        
                            "id": "33333333-3333-3333-3333-333333333333",                                                                                                                                                                        
                            "type": "WeightSet",                                                                                                                                                                                                 
                            "reps": 5,                                                                                                                                                                                                           
                            "weight": 100.0,                                                                                                                                                                                                     
                            "subCategory": "WorkSet"                                                                                                                                                                                             
                        },                                                                                                                                                                                                                       
                        {                                                                                                                                                                                                                        
                            "id": "44444444-4444-4444-4444-444444444444",                                                                                                                                                                        
                            "type": "RestSet",                                                                                                                                                                                                   
                            "timeInSeconds": 120,                                                                                                                                                                                                
                            "subCategory": "WorkSet"                                                                                                                                                                                             
                        }                                                                                                                                                                                                                        
                    ],                                                                                                                                                                                                                           
                    "exerciseType": "WEIGHT",                                                                                                                                                                                                    
                    "minReps": 5,                                                                                                                                                                                                                
                    "maxReps": 5,                                                                                                                                                                                                                
                    "lowerBoundMaxHRPercent": None,                                                                                                                                                                                              
                    "upperBoundMaxHRPercent": None,                                                                                                                                                                                              
                    "equipmentId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",                                                                                                                                                                       
                    "bodyWeightPercentage": None,                                                                                                                                                                                                
                    "generateWarmUpSets": False,                                                                                                                                                                                                 
                    "progressionMode": "OFF",                                                                                                                                                                                                    
                    "keepScreenOn": False,                                                                                                                                                                                                       
                    "showCountDownTimer": False,                                                                                                                                                                                                 
                    "intraSetRestInSeconds": None,                                                                                                                                                                                               
                    "loadJumpDefaultPct": None,                                                                                                                                                                                                  
                    "loadJumpMaxPct": None,                                                                                                                                                                                                      
                    "loadJumpOvercapUntil": None,                                                                                                                                                                                                
                    "muscleGroups": ["BACK_GLUTEAL"],                                                                                                                                                                                            
                    "secondaryMuscleGroups": ["BACK_HAMSTRING"]                                                                                                                                                                                  
                },                                                                                                                                                                                                                               
                {                                                                                                                                                                                                                                
                    "id": "55555555-5555-5555-5555-555555555555",                                                                                                                                                                                
                    "type": "Rest",                                                                                                                                                                                                              
                    "enabled": True,                                                                                                                                                                                                             
                    "timeInSeconds": 180                                                                                                                                                                                                         
                }                                                                                                                                                                                                                                
            ],                                                                                                                                                                                                                                   
            "order": 0,                                                                                                                                                                                                                          
            "enabled": True,                                                                                                                                                                                                                     
            "usePolarDevice": False,                                                                                                                                                                                                             
            "creationDate": "2026-01-06",                                                                                                                                                                                                        
            "previousVersionId": None,                                                                                                                                                                                                           
            "nextVersionId": None,
            "isActive": True,                                                                                                                                                                                                                    
            "timesCompletedInAWeek": None,                                                                                                                                                                                                       
            "globalId": "66666666-6666-6666-6666-666666666666",                                                                                                                                                                                  
            "type": 0                                                                                                                                                                                                                            
        }                                                                                                                                                                                                                                        
    ],                                                                                                                                                                                                                                           
    "name": "Push Pull Legs",
    "equipments": [
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "type": "BARBELL",
            "name": "Standard Barbell",
            "availablePlates": [
                {"weight": 20.0, "thickness": 30},
                {"weight": 15.0, "thickness": 25},
                {"weight": 10.0, "thickness": 20}
            ],
            "barWeight": 20.0,
            "sleeveLength": 200
        }
    ],
    "accessoryEquipments": []                                                                                                                                                                                                                    
}                                                                                                                                                                                                                                                   
PARALLEL_LOG_REQUEST_TRUNCATE = 8000
DEEPSEEK_CHAT_DEFAULT_TOKENS = 4000
DEEPSEEK_CHAT_MAX_TOKENS = 8000
DEEPSEEK_REASONER_DEFAULT_TOKENS = 32768
DEEPSEEK_REASONER_MAX_TOKENS = 65536

EXERCISE_TYPE_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["ExerciseType"]["enum"])
EXERCISE_CATEGORY_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["ExerciseCategory"]["enum"])
MUSCLE_GROUP_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["MuscleGroup"]["enum"])
SET_SUBCATEGORY_ENUM_VALUES = ", ".join(JSON_SCHEMA["$defs"]["SetSubCategory"]["enum"])
WORKOUT_COMPONENT_TYPE_VALUES = "Exercise, Rest, Superset"
EXACT_GENERATION_CONFIRMATION = "CONFIRM GENERATE"

BASE_SYSTEM_PROMPT = (
    "You are a workout assistant. In normal chat mode, respond conversationally. "
    "When JSON generation is requested, follow JSON-mode system prompts.\n\n"
    "CONVERSATION RULES:\n"
    "1. Detect completeness first.\n"
    "- If the user already provided a structured plan (exercise names + sets/reps + rest, often as table/day split) and asks to generate, do not ask extra discovery questions.\n"
    "- Ask clarifying questions only when essential inputs are missing.\n\n"
    "2. Equipment handling.\n"
    "- Ask about equipment only when it is not already provided.\n"
    "- If provided equipment file exists, it is immutable: never edit/remove existing items.\n"
    "- You may add missing equipment/accessories with new placeholders (EQUIPMENT_X / ACCESSORY_X).\n"
    "- Before adding weight-loaded equipment, collect required technical details.\n"
    "- If user does not know values, propose defaults and ask for confirmation.\n\n"
    "3. Recommendation quality.\n"
    "- Recommend only exercises supported by available equipment.\n"
    "- Offer feasible alternatives when required equipment is unavailable.\n"
    "- Mark unilateral intent when exercise or user request indicates single-side work.\n\n"
    "4. Preview formatting.\n"
    "- For conversational preview workouts, use a clear plain-text table.\n"
    "- The recap/preview table must show rest between sets and rest between exercises as separate, clearly labeled fields or columns.\n"
    "- Do not collapse those two rest concepts into one generic 'Rest' column when both are relevant.\n"
    "- When showing or proposing rest values, always give one exact value. Never present rest as a range such as '2:00-2:30' or '120-150s'.\n"
    "- If the source conversation gives a rest range, choose one exact value within that range and use that exact value consistently.\n"
    "- Keep notes concise and practical.\n\n"
    "5. Generation confirmation gate.\n"
    f"- Before final generation, show the workout preview/summary and tell the user to reply with exactly {EXACT_GENERATION_CONFIRMATION!r} to start generation.\n"
    f"- Call generate_workout only when the user's most recent message is exactly {EXACT_GENERATION_CONFIRMATION!r}.\n"
    "- Treat every other wording as not confirmed yet, including 'yes', 'looks good', 'go ahead', 'generate it', or paraphrases.\n"
    "- Optionally pass custom_prompt with extra constraints."
)

SUMMARIZATION_SYSTEM_PROMPT = (
    "Condense conversation history into only workout-generation-relevant facts.\n\n"
    "Include only:\n"
    "- goals, target muscles, constraints, style, duration/intensity preferences\n"
    "- available equipment (with any technical details)\n"
    "- include/exclude exercises\n"
    "- explicit prescriptions (sets, rep ranges, rest between sets, rest to next exercise, superset pairings)\n"
    "- exact load semantics for each exercise when provided\n\n"
    "Rules:\n"
    "- Remove fluff and duplicates.\n"
    "- Preserve exercise names verbatim.\n"
    "- Preserve numeric values exactly (do not broaden ranges or replace user values).\n"
    "- Rest values in the summary must be expressed as one exact number, never as a range. If the conversation gave a rest range, preserve the chosen exact rest value that will drive generation.\n"
    "- Preserve explicit superset relationships exactly, including which exercises are grouped together and any stated rest after the pair/group.\n"
    "- For BODY_WEIGHT movements, preserve all load semantics that affect baseline interpretation: added load, total effective load, bodyweight assumptions, explicit percentages, and whether the movement is full-bodyweight or partial-bodyweight.\n"
    "- If both added load and total effective load are given, keep both explicitly. Example: keep 'Weighted Ring Row +10 kg, 52.3 kg total' as both facts, not just '+10 kg vest'.\n"
    "- If the exact baseline percentage is not stated but can be inferred, preserve the raw numbers needed for that inference.\n"
    "- If information is missing/unclear, mark it explicitly without guessing."
)

JSON_SYSTEM_PROMPT = (
    "Output JSON only (no markdown/explanations). Use valid UUIDs and ISO dates (YYYY-MM-DD).\n"
    "Use only equipment IDs that exist in equipments. Do not use IRONNECK.\n\n"
    "Numeric fidelity:\n"
    "- Preserve explicit user-provided numeric values exactly.\n\n"
    "Rest semantics (strict):\n"
    "- RestSet is only inside exercise.sets (between sets of the same exercise).\n"
    "- Rest component {type:\"Rest\"} is only in workoutComponents (between exercises).\n"
    "- Never mix RestSet and Rest component locations.\n"
    "- If user gives explicit rest values, use them exactly.\n"
    "- Rest values in generated output must always be exact numbers, never ranges.\n"
    "- If the source request gives a rest range, resolve it to one exact value before output and keep that exact value consistently.\n"
    "- If not provided, pick consistent exact defaults by goal/intensity (strength usually longer than hypertrophy/endurance).\n\n"
    "Exercise validity:\n"
    "- WEIGHT -> WeightSet work sets; BODY_WEIGHT -> BodyWeightSet; COUNTUP -> EnduranceSet; COUNTDOWN -> TimedDurationSet.\n"
    "- WEIGHT/BODY_WEIGHT exercises must include minReps/maxReps > 0 and valid load percent ranges.\n"
    f"- muscleGroups must use MuscleGroup enum values only: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    "- muscleGroups may be empty only when the exercise context explicitly allows it.\n"
    f"- exerciseType must use ExerciseType enum values only: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- exerciseCategory must use ExerciseCategory enum values only: {EXERCISE_CATEGORY_ENUM_VALUES}.\n\n"
    "Text fields:\n"
    "- workout.description max 50 chars, concise and specific.\n"
    "- exercise.notes max 500 chars, concise.\n\n"
    "Optional advanced fields:\n"
    "- HR target fields and load jump tuning fields should be set only when explicitly requested; otherwise null.\n"
    "JSON Schema:\n"
    f"{json.dumps(JSON_SCHEMA, indent=2)}\n\n"
    "Example JSON Output:\n"
    f"{json.dumps(EXAMPLE_JSON, indent=2)}"
)

SELF_HEAL_SYSTEM_PROMPT = (
    "Fix JSON schema validation errors with minimal, context-aware changes.\n\n"
    "Core rules:\n"
    "- Fix only failing fields; keep valid data unchanged.\n"
    "- Preserve IDs and relationships.\n"
    "- Use valid enum values and schema-compatible types.\n"
    f"- ExerciseType enum: {EXERCISE_TYPE_ENUM_VALUES}.\n"
    f"- ExerciseCategory enum: {EXERCISE_CATEGORY_ENUM_VALUES}.\n"
    f"- MuscleGroup enum: {MUSCLE_GROUP_ENUM_VALUES}.\n"
    f"- SetSubCategory enum: {SET_SUBCATEGORY_ENUM_VALUES}.\n"
    "- Prefer semantically correct fixes (infer from exercise/workout context).\n\n"
    "Input modes:\n"
    "- Full mode: complete workout plan package JSON -> return complete corrected JSON.\n"
    "- Targeted mode: {item, itemType, context} -> return only fixed item (no wrapper).\n\n"
    "Heuristics:\n"
    "- Empty/invalid muscle groups: infer from exercise name and type.\n"
    "- Missing equipmentId: null for bodyweight, otherwise map to available equipment in context.\n"
    "- Invalid exerciseType: infer from set types.\n"
    "- Invalid load/weight values: adjust to valid ranges/combinations from equipment context.\n"
    "- Adjust advanced optional fields only when already present.\n\n"
    "Output JSON only (no markdown/explanations)."
)
# Function tool schema for OpenAI function calling
GENERATE_WORKOUT_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_workout",
        "description": f"Generate a workout JSON file based on the conversation context. Use this only when the user's most recent message is exactly {EXACT_GENERATION_CONFIRMATION!r}. Do not use it for paraphrased approval like 'yes', 'go ahead', or 'looks good'.",
        "parameters": {
            "type": "object",
            "properties": {
                "custom_prompt": {
                    "type": "string",
                    "description": "Optional additional instructions or requirements for the workout generation"
                }
            }
        }
    }
}
MUSCLE_GROUP_FIXES = {
    "BACK_QUADRICEPS": "FRONT_QUADRICEPS",
    "BACK_LATISSIMUS": "BACK_UPPER_BACK",
    "BACK_HAMSTRINGS": "BACK_HAMSTRING",
    "CORE_ABDOMINALS": "FRONT_ABS",
    "FRONT_SHOULDER": "FRONT_DELTOIDS",
    "CORE_OBLIQUE": "FRONT_OBLIQUES",
    "CHEST_PECTORAL": "FRONT_CHEST",
    "SHOULDER_ANTERIOR": "FRONT_DELTOIDS",
    "SHOULDER_LATERAL": "FRONT_DELTOIDS",
    "SHOULDER_POSTERIOR": "BACK_DELTOIDS",
    "ARM_TRICEPS": "FRONT_TRICEPS",
    "ARM_BICEPS": "FRONT_BICEPS",
    "BACK_RHOMBOID": "BACK_UPPER_BACK",
    "LATISSIMUS": "BACK_UPPER_BACK",
    "RHOMBOIDS": "BACK_UPPER_BACK",
    "PECTORALS": "FRONT_CHEST",
    "OBLIQUES": "FRONT_OBLIQUES",
    # Common variations
    "CHEST": "FRONT_CHEST",
    "QUADS": "FRONT_QUADRICEPS",
    "QUADRICEPS": "FRONT_QUADRICEPS",
    "HAMSTRINGS": "BACK_HAMSTRING",
    "HAMSTRING": "BACK_HAMSTRING",
    "GLUTES": "BACK_GLUTEAL",
    "GLUTEAL": "BACK_GLUTEAL",
    "GLUTE": "BACK_GLUTEAL",
    "BICEPS": "FRONT_BICEPS",
    "TRICEPS": "FRONT_TRICEPS",
    "SHOULDERS": "FRONT_DELTOIDS",
    "DELTS": "FRONT_DELTOIDS",
    "DELTOIDS": "FRONT_DELTOIDS",
    "ABS": "FRONT_ABS",
    "ABDOMINALS": "FRONT_ABS",
    "ABDOMINAL": "FRONT_ABS",
    "LATS": "BACK_UPPER_BACK",
    "TRAPS": "FRONT_TRAPEZIUS",
    "TRAPEZIUS": "FRONT_TRAPEZIUS",
    "CALVES": "FRONT_CALVES",
    "CALF": "FRONT_CALVES",
    "FOREARMS": "FRONT_FOREARM",
    "FOREARM": "FRONT_FOREARM",
    # Additional common typos/variations
    "QUAD": "FRONT_QUADRICEPS",
    "PECS": "FRONT_CHEST",
    "PEC": "FRONT_CHEST",
    "LOWER_BACK": "BACK_LOWER_BACK",
    "UPPER_BACK": "BACK_UPPER_BACK",
    "NECK": "FRONT_NECK",
}
