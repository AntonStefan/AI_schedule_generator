import random
from copy import deepcopy
from utils import pretty_print_timetable, read_yaml_file, acces_yaml_attributes

# Load data from YAML file
def load_data(file_path):
    return read_yaml_file(file_path)


def parse_interval(interval):
    """Parses interval formatted as '(start, end)'."""
    interval = interval.strip('()')  # Remove the parentheses
    start, end = interval.split(',')
    return (int(start.strip()), int(end.strip()))


def split_time_range(time_range, interval_length=2):
    start, end = map(int, time_range.split('-'))
    return [(i, i + interval_length) for i in range(start, end, interval_length)]


def preprocess_constraints(constraints):
    new_constraints = []
    days = ['Luni', 'Marti', 'Miercuri', 'Joi', 'Vineri','!Luni', '!Marti', '!Miercuri', '!Joi', '!Vineri' ]
    for constraint in constraints:
        is_disallowed = constraint.startswith('!') and constraint not in days
        if is_disallowed:
            constraint = constraint[1:]  # Remove the '!' for processing

        if '-' in constraint:
            intervals = split_time_range(constraint)
            for interval in intervals:
                formatted_interval = f"{interval[0]}-{interval[1]}"
                if is_disallowed:
                    new_constraints.append(f"!{formatted_interval}")
                else:
                    new_constraints.append(formatted_interval)
        else:
            new_constraints.append(constraint)
    return new_constraints


def initialize_state(data):

    # Parse data to create a complex state representation
    interv = [parse_interval(interval) for interval in data['Intervale']]
    state = {
        'days': data['Zile'],
        'intervals': interv,
        'rooms': {room_name: {
                      'capacity': room_info['Capacitate'],
                      'allowed_subjects': room_info['Materii']
                  } for room_name, room_info in data['Sali'].items()},
        'courses': {course_name: {
                      'student_count': num_students,  # Total students registered for the course
                      'assigned_students': 0  # Students successfully assigned to this course
                  } for course_name, num_students in data['Materii'].items()},
        'professors': {prof_name: {
                          'constraints': preprocess_constraints(prof_info.get('Constrangeri', [])),
                          'subjects': prof_info.get('Materii', []),
                          'scheduled_hours': 0 # Track scheduled hours to adhere to constraints
                      } for prof_name, prof_info in data['Profesori'].items()},
        'schedule': {day: {interval: {room: None for room in data['Sali']}
                    for interval in [parse_interval(i) for i in data['Intervale']]} 
                for day in data['Zile']},
        'student_needs': {course: students for course, students in data['Materii'].items()}  # Each course needs a certain number of students
    }
    return state


def check_hard_constraints_cost(state):
    violations = []
    cost = 0

    # Check for each day and each interval in that day
    for day, intervals in state['schedule'].items():
        seen_professors = {}

        for interval, rooms in intervals.items():
            for room, assignment in rooms.items():
                if assignment is not None:
                    professor, course = assignment

                    # Check if a professor is scheduled more than once in the same interval
                    if professor in seen_professors and interval in seen_professors[professor]:
                        violations.append(f"Professor {professor} is double-booked during {interval} on {day}.")
                    seen_professors.setdefault(professor, set()).add(interval)

                    # Check maximum hours per week for each professor
                    if state['professors'][professor]['scheduled_hours'] > 7:
                        violations.append(f"Professor {professor} exceeds the maximum 7 intervals per week.")

                    # Check if the course is allowed in the room
                    if course not in state['rooms'][room]['allowed_subjects']:
                        violations.append(f"Course {course} is not allowed in room {room}.")

                    # Check if all student needs are met
                    unmet_needs = [state['student_needs'][course] for course in state['student_needs'] if state['student_needs'][course] > 0]
                    if unmet_needs:
                        cost = sum(unmet_needs)
                    
    return  5 * cost + 10 * len(violations)


def check_soft_constraints_cost(state):
    soft_violations = []

    # Iterate over each professor and their constraints
    for prof_name, prof_info in state['professors'].items():
        prof_constraints = prof_info['constraints']
        
        # Define non-preferred days and intervals separately
        non_preferred_days = [constr[1:] for constr in prof_constraints if constr.startswith('!') and '-' not in constr]
        non_preferred_intervals = [constr[1:] for constr in prof_constraints if constr.startswith('!') and '-' in constr]

        for day, intervals in state['schedule'].items():

            # Check if the current day is non-preferred
            day_violation = any(day == np_day for np_day in non_preferred_days)

            for interval, rooms in intervals.items():
                interval_str = f"{interval[0]}-{interval[1]}"

                # Check if the current interval is non-preferred
                interval_violation = any(interval_str == np_interval for np_interval in non_preferred_intervals)

                for room, assignment in rooms.items():
                    if assignment and assignment[0] == prof_name:
                        if day_violation:

                            # Append violation for non-preferred day
                            soft_violations.append(f"Professor {prof_name} is scheduled to teach on non-preferred day {day} during {interval}.")
                        if interval_violation:

                            # Append violation for non-preferred interval
                            soft_violations.append(f"Professor {prof_name} is scheduled to teach during non-preferred interval {interval_str} on {day}.")

    return len(soft_violations)


def make_initial_assignment(state):

    sorted_rooms = sorted(state['rooms'].items(), key=lambda item: -item[1]['capacity'])

    for day in state['days']:
        for interval in state['intervals']:
            assigned_professors_this_interval = set()

            # Sort courses by descending student needs for dynamic handling
            sorted_courses = sorted(state['student_needs'].items(), key=lambda item: -item[1])
            for course_name, num_students in sorted_courses:
                if num_students > 0:
                    for room_name, room_details in sorted_rooms:
                        if state['schedule'][day][interval][room_name] is None and course_name in room_details['allowed_subjects']:
                            interval_str = f"{interval[0]}-{interval[1]}"
                            possible_profs = [
                                prof for prof, details in state['professors'].items()
                                if course_name in details['subjects'] and
                                   details['scheduled_hours'] < 7 and  # Ensure not exceeding weekly limit
                                   prof not in assigned_professors_this_interval and
                                   day not in [c.strip('!') for c in details['constraints'] if c.startswith('!')] and
                                   (day in details['constraints'] or str(interval) in details['constraints'] or not details['constraints']) and
                                    interval_str not in [c.strip('!') for c in details['constraints'] if c.startswith('!')] and
                                   (interval_str in details['constraints'] or not details['constraints'])
                            ]

                            possible_profs = sorted(possible_profs, key=lambda prof: state['professors'][prof]['scheduled_hours'])          
                            if possible_profs:
                                chosen_prof = random.choice(possible_profs) 
                                assign_count = min(room_details['capacity'], num_students)
                                state['schedule'][day][interval][room_name] = (chosen_prof, course_name)
                                state['professors'][chosen_prof]['scheduled_hours'] += 1  # Increment hours scheduled for the week
                                state['student_needs'][course_name] -= assign_count
                                assigned_professors_this_interval.add(chosen_prof)
                                return state



def get_course_room_availability(rooms, course):

    # Returnează numărul de săli disponibile pentru un curs
    return sum(course in room_info['allowed_subjects'] for room_name, room_info in rooms.items())


def get_all_possible_states(current_state):
    new_states = []

    # Sort rooms by capacity in descending order
    sorted_rooms = sorted(current_state['rooms'].items(), key=lambda item: -item[1]['capacity'])
    for day in current_state['days']:
        for interval in current_state['intervals']:
            assigned_professors_this_interval = set()
            course_availability = {course: get_course_room_availability(current_state['rooms'], course)
                           for course in current_state['courses']}

            # Sort courses by descending student needs an availability
            sorted_courses = sorted(current_state['student_needs'].items(), key=lambda item: course_availability[item[0]])

            for course_name, num_students in sorted_courses:
                if num_students > 0:
                    for room_name, room_details in sorted_rooms:
                        if current_state['schedule'][day][interval][room_name] is None and course_name in room_details['allowed_subjects']:

                            # Loop through professors to find eligible ones for the current course and room
                            for prof_name, prof_info in current_state['professors'].items():
                                if prof_name not in assigned_professors_this_interval and \
                                   course_name in prof_info['subjects'] and \
                                   prof_info['scheduled_hours'] < 7:  # Ensure they're under their max hours
                                    
                                    # Create a new state with the current assignment
                                    new_state = deepcopy(current_state)
                                    new_state['schedule'][day][interval][room_name] = (prof_name, course_name)
                                    new_state['professors'][prof_name]['scheduled_hours'] += 1
                                    new_state['student_needs'][course_name] -= room_details['capacity']
                                    assigned_professors_this_interval.add(prof_name)

                                    # Append the new state to the list
                                    new_states.append(new_state)
                                    

    return new_states


def are_student_needs_met(student_needs):
    """ Check if all students has been assigned """
    return all(needs == 0 for needs in student_needs.values())


def hill_climbing(initial_state, max_iters=1000):
    iters = 0  # Number of iterations
    current_state = make_initial_assignment(initial_state)
    print("Initial state:", current_state)
    best_state = current_state
    best_cost = combined_cost(current_state)

    while iters < max_iters:
        iters += 1  # Incrementing number of iterations

        if are_student_needs_met(current_state['student_needs']):       
            print("All student needs are met. Schedule is complete.")
            break

        next_states = get_all_possible_states(current_state)
        if not next_states:
            print("No more states to explore.")
            break

        # Chose the state with the minimum cost to explore next
        next_state = min(next_states, key=combined_cost)
        next_cost =  combined_cost(next_state)

        if next_cost < best_cost:
            print("\n")
            print("\n")
            print("\n")
            print(next_cost)
            print("Found a better state.")
            print(next_state['schedule'])
            print("\n")
            print("\n")
            print("\n")

            # Found best state
            best_state = next_state
            best_cost = next_cost
            current_state = next_state  # Continue searching from the best state

    print("Best state found with cost:", best_cost)
    print("Numer of iterations:", iters)
    return best_state


def combined_cost(state):
    return check_soft_constraints_cost(state) + check_hard_constraints_cost(state)



# Monte-Carlo Tree Search Algorithm
def monte_carlo_tree_search(initial_state):
    # Implement the MCTS logic here
    pass

# Main function to run the scheduling algorithm
def run_algorithm(algorithm, data_file):
    data = load_data(data_file)
    acces_yaml_attributes(data)
    initial_state = initialize_state(data)
    
    if algorithm == 'hc':
        solution = hill_climbing(initial_state)
    elif algorithm == 'mcts':
        solution = monte_carlo_tree_search(initial_state)

    if solution:
        print("\n")
        output = pretty_print_timetable(solution['schedule'], data_file)  # Gather pretty printed schedule
        print(output)
        print(combined_cost(solution))
        output_path = 'outputs/dummy.txt'  # Define output path
        with open(output_path, 'w') as file:  # Write the schedule to a file
            file.write(output)
        print(f"Results written to {output_path}")
        

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python orar.py [algorithm: hc|mcts] [data_file.yaml]")
    else:
        algorithm = sys.argv[1]
        data_file = sys.argv[2]
        run_algorithm(algorithm, data_file)
