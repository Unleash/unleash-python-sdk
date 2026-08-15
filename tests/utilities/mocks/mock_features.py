MOCK_FEATURE_RESPONSE = {
    "version": 1,
    "features": [
        {
            "name": "testFlag",
            "description": "This is a test!",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2018-10-04T01:27:28.477Z",
            "impressionData": True,
        },
        {
            "name": "testFlag2",
            "description": "Test flag 2",
            "enabled": True,
            "strategies": [
                {"name": "gradualRolloutRandom", "parameters": {"percentage": "50"}}
            ],
            "createdAt": "2018-10-04T11:03:56.062Z",
            "impressionData": False,
        },
        {
            "name": "testContextFlag",
            "description": "This is a test for static context fileds!",
            "enabled": True,
            "strategies": [
                {"name": "custom-context", "parameters": {"environments": "prod"}}
            ],
            "createdAt": "2018-10-04T01:27:28.477Z",
            "impressionData": False,
        },
        {
            "name": "testConstraintFlag",
            "description": "This is a flag with a constraint!",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                    "constraints": [
                        {
                            "contextName": "currentTime",
                            "operator": "DATE_BEFORE",
                            "value": "2022-01-22T00:00:00.000Z",
                            "inverted": False,
                        }
                    ],
                },
            ],
            "createdAt": "2018-10-04T01:27:28.477Z",
            "impressionData": False,
        },
        {
            "name": "testVariations",
            "description": "Test variation",
            "enabled": True,
            "strategies": [{"name": "userWithId", "parameters": {"userIds": "2"}}],
            "variants": [
                {
                    "name": "VarA",
                    "weight": 34,
                    "payload": {"type": "string", "value": "Test1"},
                    "overrides": [
                        {
                            "contextName": "userId",
                            "values": ["ivanklee86@gmail.com", "ivan@aaptiv.com"],
                        }
                    ],
                },
                {
                    "name": "VarB",
                    "weight": 33,
                    "payload": {"type": "string", "value": "Test 2"},
                },
                {
                    "name": "VarC",
                    "weight": 33,
                    "payload": {"type": "string", "value": "Test 3"},
                },
            ],
            "createdAt": "2019-10-25T13:22:02.035Z",
            "impressionData": True,
        },
    ],
}

MOCK_FEATURES_WITH_SEGMENTS_RESPONSE = {
    "version": 2,
    "features": [
        {
            "strategies": [
                {
                    "name": "default",
                    "constraints": [],
                    "parameters": {},
                    "segments": [1, 2],
                }
            ],
            "impressionData": False,
            "enabled": True,
            "name": "Test",
            "description": "",
            "project": "default",
            "type": "release",
            "variants": [],
        }
    ],
    "query": {"environment": "development", "inlineSegmentConstraints": False},
    "segments": [
        {
            "id": 1,
            "name": "TestSegment1",
            "description": "test",
            "constraints": [
                {
                    "value": "2022-06-14T06:40:17.766Z",
                    "values": [],
                    "inverted": False,
                    "operator": "DATE_BEFORE",
                    "contextName": "currentTime",
                    "caseInsensitive": False,
                }
            ],
            "createdBy": "admin",
            "createdAt": "2022-06-14T06:40:25.331Z",
        },
        {
            "id": 2,
            "name": "TestSegment2",
            "description": "test",
            "constraints": [
                {
                    "value": "2022-06-14T06:40:17.766Z",
                    "values": [],
                    "inverted": False,
                    "operator": "DATE_AFTER",
                    "contextName": "currentTime",
                    "caseInsensitive": False,
                }
            ],
            "createdBy": "admin",
            "createdAt": "2022-06-14T06:40:25.331Z",
        },
    ],
}

MOCK_FEATURE_RESPONSE_PROJECT = {
    "version": 1,
    "features": [
        {
            "name": "ivan-project",
            "type": "release",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "variants": [],
            "createdAt": "2023-01-24T06:40:25.331Z",
            "impressionData": False,
        }
    ],
}

# A delta, as the streaming endpoint sends on `unleash-updated`. It describes
# one flag; every other flag the engine knows about survives.
MOCK_FEATURE_DELTA_RESPONSE = {
    "events": [
        {
            "type": "feature-updated",
            "eventId": 2,
            "feature": {
                "name": "deltaFlag",
                "type": "release",
                "enabled": True,
                "strategies": [{"name": "default", "parameters": {}}],
                "variants": [],
                "impressionData": False,
            },
        }
    ]
}

MOCK_FEATURE_WITH_DEPENDENCIES_RESPONSE = {
    "version": 1,
    "features": [
        {
            "name": "Parent",
            "description": "Dependency on Child feature toggle",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                    "variants": [
                        {
                            "name": "variant1",
                            "weight": 1000,
                            "stickiness": "default",
                            "weightType": "variable",
                        }
                    ],
                }
            ],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
        },
        {
            "name": "Child",
            "description": "Feature toggle that depends on Parent feature toggle",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
            "dependencies": [
                {
                    "feature": "Parent",
                }
            ],
        },
        {
            "name": "ChildWithVariant",
            "description": "Feature toggle with variant that depends on a specific variant of the Parent feature toggle",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                    "variants": [
                        {
                            "name": "childVariant",
                            "weight": 1000,
                            "stickiness": "default",
                            "weightType": "variable",
                        }
                    ],
                }
            ],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
            "dependencies": [
                {
                    "feature": "Parent",
                    "variants": ["variant1"],
                }
            ],
        },
        {
            "name": "Disabled",
            "description": "Disabled feature toggle",
            "enabled": False,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2023-10-06T11:53:02.161Z",
            "impressionData": False,
        },
        {
            "name": "WithDisabledDependency",
            "description": "Feature toggle that depends on Parent feature toggle",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2023-10-06T12:04:05.667Z",
            "impressionData": False,
            "dependencies": [
                {
                    "feature": "Disabled",
                }
            ],
        },
        {
            "name": "ComplexExample",
            "description": "Feature toggle that depends on multiple feature toggles",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2023-10-06T12:04:05.667Z",
            "impressionData": False,
            "dependencies": [
                {"feature": "Parent", "variants": ["variant1"]},
                {
                    "feature": "Disabled",
                    "enabled": False,
                },
            ],
        },
        {
            "name": "UnlistedDependency",
            "description": "Feature toggle that depends on a feature toggle that does not exist",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2023-10-06T12:04:05.667Z",
            "impressionData": False,
            "dependencies": [{"feature": "DoesNotExist"}],
        },
        {
            "name": "TransitiveDependency",
            "description": "Feature toggle that depends on a feature toggle that has a dependency",
            "enabled": True,
            "strategies": [{"name": "default", "parameters": {}}],
            "createdAt": "2023-10-06T12:04:05.667Z",
            "impressionData": False,
            "dependencies": [{"feature": "Child"}],
        },
    ],
}

MOCK_FEATURE_ENABLED_NO_VARIANTS_RESPONSE = {
    "version": 1,
    "features": [
        {
            "name": "EnabledNoVariants",
            "description": "Enabled with no variants",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                }
            ],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
        },
    ],
}

MOCK_FEATURE_WITH_NUMERIC_CONSTRAINT = {
    "version": 1,
    "features": [
        {
            "name": "NumericConstraint",
            "description": "Feature toggle with numeric constraint",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                    "constraints": [
                        {
                            "contextName": "userId",
                            "operator": "NUM_GT",
                            "value": "10",
                            "inverted": False,
                        }
                    ],
                }
            ],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
        },
    ],
}

MOCK_FEATURE_WITH_DATE_AFTER_CONSTRAINT = {
    "version": 1,
    "features": [
        {
            "name": "DateConstraint",
            "description": "Feature toggle with numeric constraint",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                    "constraints": [
                        {
                            "contextName": "currentTime",
                            "operator": "DATE_AFTER",
                            "value": "1988-06-15T06:40:17.766Z",
                            "inverted": False,
                        }
                    ],
                }
            ],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
        },
    ],
}

MOCK_FEATURE_WITH_CUSTOM_CONTEXT_REQUIREMENTS = {
    "version": 1,
    "features": [
        {
            "name": "customContextToggle",
            "description": "Feature toggle with custom context constraint",
            "enabled": True,
            "strategies": [
                {
                    "name": "default",
                    "parameters": {},
                    "constraints": [
                        {
                            "contextName": "myContext",
                            "operator": "IN",
                            "values": ["1234"],
                            "inverted": False,
                        }
                    ],
                }
            ],
            "createdAt": "2018-10-09T06:04:05.667Z",
            "impressionData": False,
        },
    ],
}
